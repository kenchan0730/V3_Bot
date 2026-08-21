import pandas as pd
import pytest

from backtest.engine import BacktestEngine, BacktestResult
from core.correlation import clustered_pairs, correlation_matrix, weekly_returns
from tests.conftest import make_ohlcv


CONFIG = {
    "risk": {"max_risk_percent": 2.0, "max_position_pct": 50.0},
    "portfolio": {"max_open_positions": 3, "max_symbol_pct": 60.0, "max_total_open_risk_pct": 10.0},
    "trading": {"price_limit": 1000, "max_shares": 100},
    "zscore": {"best_zone_min": 0.5},
}


def test_result_metrics_with_no_trades():
    result = BacktestResult(1000.0)
    assert result.total_return_pct == 0.0
    assert result.win_rate == 0.0
    assert result.max_drawdown_pct == 0.0


def test_result_metrics_with_trades():
    result = BacktestResult(1000.0)
    result.add_trade({"pnl": 100.0})
    result.add_trade({"pnl": -50.0})
    result.equity_curve = [(0, 1000.0), (1, 1100.0), (2, 1050.0)]
    assert result.win_rate == pytest.approx(50.0)
    assert result.profit_factor == pytest.approx(2.0)
    assert result.max_drawdown_pct > 0
    assert result.final_capital == 1050.0


def test_profit_factor_all_wins():
    result = BacktestResult(1000.0)
    result.add_trade({"pnl": 10.0})
    assert result.profit_factor == float("inf")


def test_summary_keys():
    result = BacktestResult(1000.0)
    result.add_trade({"pnl": 5.0})
    summary = result.summary()
    for key in ("initial_capital", "final_capital", "total_return_pct", "trades",
                "win_rate_pct", "profit_factor", "max_drawdown_pct"):
        assert key in summary


def test_engine_runs_on_trending_data():
    closes = [10 + i * 0.08 for i in range(160)]
    df = make_ohlcv(closes)
    engine = BacktestEngine(CONFIG, initial_capital=10000.0, warmup_bars=60, max_hold_bars=10)
    result = engine.run("TEST", df)
    assert isinstance(result, BacktestResult)
    assert len(result.equity_curve) > 0


def test_engine_handles_uppercase_columns():
    df = make_ohlcv([10 + i * 0.05 for i in range(140)]).rename(columns=str.capitalize)
    engine = BacktestEngine(CONFIG, initial_capital=5000.0)
    result = engine.run("TEST", df)
    assert result.summary()["initial_capital"] == 5000.0


def test_engine_no_trades_on_flat_data():
    df = make_ohlcv([10.0] * 140)
    engine = BacktestEngine(CONFIG, initial_capital=5000.0)
    result = engine.run("FLAT", df)
    assert len(result.trades) == 0


def test_engine_check_exit_stop():
    engine = BacktestEngine(CONFIG)
    bar = pd.Series({"low": 9.0, "high": 11.0, "close": 10.0})
    price, reason = engine._check_exit(bar, {"stop": 9.5, "target": 12.0, "index": 0}, 1)
    assert reason == "STOP" and price == 9.5


def test_engine_check_exit_target():
    engine = BacktestEngine(CONFIG)
    bar = pd.Series({"low": 10.0, "high": 13.0, "close": 12.5})
    price, reason = engine._check_exit(bar, {"stop": 9.0, "target": 12.0, "index": 0}, 1)
    assert reason == "TARGET" and price == 12.0


def test_engine_check_exit_timeout():
    engine = BacktestEngine(CONFIG, max_hold_bars=5)
    bar = pd.Series({"low": 10.0, "high": 11.0, "close": 10.5})
    price, reason = engine._check_exit(bar, {"stop": 9.0, "target": 20.0, "index": 0}, 5)
    assert reason == "TIMEOUT" and price == 10.5


def test_engine_check_exit_none():
    engine = BacktestEngine(CONFIG, max_hold_bars=50)
    bar = pd.Series({"low": 10.0, "high": 11.0, "close": 10.5})
    price, reason = engine._check_exit(bar, {"stop": 9.0, "target": 20.0, "index": 0}, 1)
    assert price is None and reason is None


# ----- correlation -----

def test_weekly_returns_length():
    index = pd.bdate_range("2024-01-01", periods=60)
    series = pd.Series([10 + i * 0.1 for i in range(60)], index=index)
    returns = weekly_returns(series)
    assert len(returns) > 5


def test_weekly_returns_empty_input():
    assert len(weekly_returns(pd.Series(dtype="float64"))) == 0


def test_correlation_matrix_identifies_pairs():
    index = pd.bdate_range("2024-01-01", periods=120)
    base = pd.Series([10 + i * 0.1 for i in range(120)], index=index)
    closes = {"AAA": base, "BBB": base * 1.02, "CCC": base.iloc[::-1].reset_index(drop=True).set_axis(index)}
    matrix = correlation_matrix(closes)
    assert not matrix.empty
    pairs = clustered_pairs(matrix, threshold=0.9)
    assert any("AAA" in pair and "BBB" in pair for pair in pairs)


def test_correlation_matrix_insufficient_data():
    assert correlation_matrix({"AAA": pd.Series([1.0, 2.0])}).empty


def test_clustered_pairs_empty_matrix():
    assert clustered_pairs(pd.DataFrame()) == []
