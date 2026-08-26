"""Backtest must not flatter itself: costs and the live approval chain apply.

Without commissions, slippage and the ProfessionalMind gate, replayed results
systematically overstate what live trading can achieve.
"""

import pytest

from backtest.engine import BacktestEngine
from core.professional_mind import ProfessionalMind
from tests.helpers import make_ohlcv

CONFIG = {
    "risk": {"max_risk_percent": 2.0, "max_position_pct": 50.0},
    "portfolio": {"max_open_positions": 3, "max_symbol_pct": 60.0,
                  "max_total_open_risk_pct": 10.0},
    "trading": {"price_limit": 1000, "max_shares": 100},
    "zscore": {"best_zone_min": 0.5},
    "execution": {"slippage_ticks": 1, "tick_size": 0.01},
    # These tests target the cost model and the mind approval chain, so the
    # retail and pacing layers are held out; they have their own tests.
    "backtest": {"apply_costs": True, "commission_per_share": 0.005,
                 "commission_minimum": 1.0, "exit_slippage_ticks": 1,
                 "use_retail_mind": False, "use_pacing": False},
}


def _df():
    """Rising series with periodic hammer + volume spikes so entries actually fire."""
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


def _run(engine):
    return engine.run("TEST", _df())


def test_commission_uses_per_order_minimum():
    engine = BacktestEngine(CONFIG, initial_capital=10000.0)
    assert engine.commission(10) == pytest.approx(1.0)
    assert engine.commission(1000) == pytest.approx(5.0)
    assert engine.commission(0) == 0.0


def test_entry_slippage_matches_live_helper():
    engine = BacktestEngine(CONFIG, initial_capital=10000.0)
    assert engine.entry_with_slippage(12.00) == pytest.approx(12.01)
    assert engine.exit_with_slippage(12.00) == pytest.approx(11.99)


def test_costs_can_be_disabled_for_comparison():
    cfg = {**CONFIG, "backtest": {**CONFIG["backtest"], "apply_costs": False}}
    engine = BacktestEngine(cfg, initial_capital=10000.0)
    assert engine.commission(100) == 0.0
    assert engine.entry_with_slippage(12.00) == pytest.approx(12.00)


def test_synthetic_data_actually_trades():
    """Guard the fixture: the realism assertions below need real trades."""
    result = _run(BacktestEngine(CONFIG, initial_capital=10000.0, max_hold_bars=10))
    assert len(result.trades) > 0


def test_costs_reduce_net_pnl_versus_gross():
    result = _run(BacktestEngine(CONFIG, initial_capital=10000.0, max_hold_bars=10))
    assert result.trades
    for trade in result.trades:
        assert trade["pnl"] == pytest.approx(trade["gross_pnl"] - trade["costs"])
        assert trade["costs"] > 0


def test_summary_exposes_costs_and_rejections():
    summary = _run(BacktestEngine(CONFIG, initial_capital=10000.0, max_hold_bars=10)).summary()
    assert summary["total_costs"] > 0
    assert "mind_rejections" in summary


def test_costed_run_underperforms_frictionless():
    frictionless = {**CONFIG, "backtest": {**CONFIG["backtest"], "apply_costs": False}}
    costed = _run(BacktestEngine(CONFIG, initial_capital=10000.0, max_hold_bars=10))
    ideal = _run(BacktestEngine(frictionless, initial_capital=10000.0, max_hold_bars=10))
    assert costed.trades and ideal.trades
    assert costed.final_capital < ideal.final_capital


def test_professional_mind_gate_reduces_or_matches_trades():
    mind = ProfessionalMind({
        "enabled": True, "log_every_deliberation": False,
        "liquidity": {"enabled": True, "avoid_first_minutes": 0, "avoid_last_minutes": 0},
    })
    plain = _run(BacktestEngine(CONFIG, initial_capital=10000.0, max_hold_bars=10))
    gated = _run(BacktestEngine(
        CONFIG, initial_capital=10000.0, max_hold_bars=10, professional_mind=mind,
    ))
    assert len(gated.trades) <= len(plain.trades)


class _RejectAll:
    def approve_entry(self, *args, **kwargs):
        from core.professional_mind import MindDecision
        return MindDecision(approve=False, action="REJECT", reasons=["test"])

    def conviction_factor(self, score):
        return 1.0


class _ZeroConviction:
    def approve_entry(self, *args, **kwargs):
        from core.professional_mind import MindDecision
        return MindDecision(approve=True, action="PROCEED", execution_score=2)

    def conviction_factor(self, score):
        return 0.0


class _Exploding:
    def approve_entry(self, *args, **kwargs):
        raise RuntimeError("boom")

    def conviction_factor(self, score):
        return 1.0


def test_mind_rejections_block_and_are_counted():
    result = _run(BacktestEngine(
        CONFIG, initial_capital=10000.0, max_hold_bars=10, professional_mind=_RejectAll(),
    ))
    assert result.trades == []
    assert result.mind_rejections > 0


def test_zero_conviction_blocks_entry():
    result = _run(BacktestEngine(
        CONFIG, initial_capital=10000.0, max_hold_bars=10,
        professional_mind=_ZeroConviction(),
    ))
    assert result.trades == []
    assert result.mind_rejections > 0


def test_mind_failure_rejects_entries_not_fail_open():
    """Mind exceptions must reject entries (E1) — backtest must not silently approve."""
    result = _run(BacktestEngine(
        CONFIG, initial_capital=10000.0, max_hold_bars=10, professional_mind=_Exploding(),
    ))
    assert result.trades == []
    assert result.mind_rejections > 0


# ----- retail / pacing layers -----

RETAIL_CONFIG = {
    **CONFIG,
    "backtest": {**CONFIG["backtest"], "use_retail_mind": True},
}


def test_retail_layer_filters_and_is_counted():
    plain = _run(BacktestEngine(CONFIG, initial_capital=10000.0, max_hold_bars=10))
    retail = _run(BacktestEngine(RETAIL_CONFIG, initial_capital=10000.0, max_hold_bars=10))
    assert len(retail.trades) <= len(plain.trades)
    assert retail.summary()["retail_rejections"] >= 0


def test_summary_reports_monthly_frequency():
    summary = _run(BacktestEngine(CONFIG, initial_capital=10000.0, max_hold_bars=10)).summary()
    assert summary["trades_per_month"] > 0


def test_pacing_hard_cap_limits_trade_count():
    capped = BacktestEngine(
        {**CONFIG, "backtest": {**CONFIG["backtest"], "use_pacing": True},
         "trade_pacing": {"target_trades_per_month": 1, "max_trades_per_month": 1}},
        initial_capital=10000.0, max_hold_bars=10, pacing_target=1,
    )
    uncapped = BacktestEngine(CONFIG, initial_capital=10000.0, max_hold_bars=10)
    assert len(_run(capped).trades) <= len(_run(uncapped).trades)
