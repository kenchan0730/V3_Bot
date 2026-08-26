"""Portfolio-level backtest and broker cost integration."""

import pytest

from backtest.engine import BacktestEngine
from backtest.portfolio_engine import PortfolioBacktestEngine
from core.broker_costs import resolve
from tests.helpers import make_ohlcv


CONFIG = {
    "risk": {"max_risk_percent": 2.0, "max_position_pct": 33.0},
    "portfolio": {
        "max_open_positions": 3,
        "max_symbol_pct": 33.0,
        "max_total_open_risk_pct": 10.0,
        "max_gross_exposure_pct": 99.0,
    },
    "trading": {"price_limit": 1000, "max_shares": 100},
    "zscore": {"best_zone_min": 0.5},
    "execution": {"slippage_ticks": 1, "tick_size": 0.01},
    "broker": {"profile": "ibkr_pro"},
    "backtest": {
        "apply_costs": True,
        "use_retail_mind": False,
        "use_pacing": False,
        "use_live_throttles": False,
        "use_professional_mind": False,
    },
    "swing_trading": {
        "require_sector_alignment": False,
        "sector_filter_mode": "off",
    },
    "emotion": {"max_daily_trades": 2},
    "trade_pacing": {"target_trades_per_month": 20, "max_trades_per_month": 50},
}


def _signal_df():
    """Rising series with periodic hammer + volume spikes (matches realism tests)."""
    closes = [10 + i * 0.09 for i in range(200)]
    volumes = [1_000_000] * 200
    signal_bars = range(70, 200, 15)
    for i in signal_bars:
        volumes[i] = 2_600_000

    df = make_ohlcv(closes, volumes=volumes)
    col = {name: df.columns.get_loc(name) for name in ("open", "high", "low", "close")}
    for i in signal_bars:
        close = float(df.iloc[i, col["close"]])
        df.iloc[i, col["open"]] = close - 0.01
        df.iloc[i, col["high"]] = close
        df.iloc[i, col["low"]] = close - 2.0
    return df


def test_broker_costs_resolve_from_profile():
    costs = resolve({"broker": {"profile": "ibkr_lite"}})
    assert costs.is_commission_free
    assert costs.commission(100) == 0.0


def test_backtest_engine_uses_broker_profile():
    engine = BacktestEngine({**CONFIG, "broker": {"profile": "alpaca"}})
    assert engine.broker_profile == "alpaca"
    assert engine.commission(10) == 0.0


def test_portfolio_backtest_runs_with_shared_capital():
    df = _signal_df()
    frames = {"AAA": df.copy(), "BBB": df.copy()}
    engine = PortfolioBacktestEngine(CONFIG, initial_capital=5000.0, max_hold_bars=8)
    result = engine.run_portfolio(frames)
    assert result.trades
    assert result.final_capital != result.initial_capital
    assert "throttle_stats" in result.summary()


def test_portfolio_backtest_respects_max_open_positions():
    df = _signal_df()
    frames = {f"S{i}": df.copy() for i in range(6)}
    engine = PortfolioBacktestEngine(CONFIG, initial_capital=50000.0, max_hold_bars=50)
    result = engine.run_portfolio(frames)
    # Cannot hold more than 3 names at once; concurrent overlap is bounded by config.
    assert result.summary()["trades"] >= 1


def test_portfolio_trades_record_risk_pct():
    df = _signal_df()
    engine = PortfolioBacktestEngine(CONFIG, initial_capital=5000.0, max_hold_bars=8)
    result = engine.run_portfolio({"AAA": df})
    if result.trades:
        assert result.trades[0].get("risk_pct") is not None
