"""Live vs backtest entry path parity — same EntryPipeline, documented floor delta."""

import pytest

from core.entry_pipeline import EntryPipeline
from core.intraday_engine import IntradayEngine
from core.portfolio import Portfolio
from core.professional_mind import MindDecision, ProfessionalMind
from core.risk_manager import RiskManager
from tests.helpers import make_ohlcv


CONFIG = {
    "risk": {"max_risk_percent": 2.0, "max_position_pct": 20.0},
    "portfolio": {
        "max_gross_exposure_pct": 60.0,
        "max_open_positions": 5,
        "max_symbol_pct": 20.0,
        "max_total_open_risk_pct": 6.0,
    },
}


def _pipeline(min_shares):
    risk = RiskManager(initial_capital=1275.0, config=CONFIG["risk"])
    portfolio = Portfolio(CONFIG["portfolio"])
    mind = ProfessionalMind({"enabled": False, "log_every_deliberation": False})
    intraday = IntradayEngine({"enabled": False})
    return EntryPipeline(
        risk, portfolio, mind, intraday,
        slippage_ticks=1, tick_size=0.01,
        price_limit=40.0, max_shares=20,
        min_shares=min_shares,
    )


def _signal():
    return {
        "action": "STRONG_BUY",
        "entry": 10.0,
        "stop": 9.0,
        "target1": 12.0,
    }


def test_parity_with_same_min_shares_floor():
    """Live and backtest match when min_shares floor is equal."""
    live = _pipeline(min_shares=0)
    backtest = _pipeline(min_shares=0)
    df = make_ohlcv([10.0] * 80)
    kwargs = dict(
        exposure=100, allow_intraday_entries=False, current_regime="NEUTRAL",
        allow_new_entries=True, vix=18.0, zscore_min=0.5, intraday_mode=False,
    )
    live_result = live.run("AVAH", _signal(), quant={}, df=df, **kwargs)
    bt_result = backtest.run("AVAH", _signal(), quant={}, df=df, **kwargs)
    assert live_result.proceed and bt_result.proceed
    assert live_result.entry == bt_result.entry
    assert live_result.shares == bt_result.shares
    assert live_result.stop == bt_result.stop


def test_documented_floor_delta_live_vs_backtest():
    """Live min_shares=1 can keep 1 share when scaled down to zero in backtest."""
    live = _pipeline(min_shares=1)
    backtest = _pipeline(min_shares=0)

    class ScalingMind:
        cfg = {"enabled": True}

        def approve_entry(self, *args, **kwargs):
            return MindDecision(approve=True, execution_score=10, shares_scale=0.01)

        def conviction_factor(self, score):
            return 1.0

    live.professional = ScalingMind()
    backtest.professional = ScalingMind()
    df = make_ohlcv([10.0] * 80)
    kwargs = dict(
        exposure=100, allow_intraday_entries=False, current_regime="NEUTRAL",
        allow_new_entries=True, vix=18.0, zscore_min=0.5, intraday_mode=False,
    )
    live_result = live.run("AVAH", _signal(), quant={}, df=df, **kwargs)
    bt_result = backtest.run("AVAH", _signal(), quant={}, df=df, **kwargs)
    assert live_result.proceed is True
    assert live_result.shares >= 1
    assert bt_result.proceed is False or bt_result.shares == 0


def test_mind_exception_rejects_entry(pipeline=None):
    """Mind errors must reject — no fail-open (E1)."""
    pipe = _pipeline(min_shares=0)

    class BrokenMind:
        cfg = {"enabled": True}

        def approve_entry(self, *args, **kwargs):
            raise RuntimeError("simulated mind failure")

    pipe.professional = BrokenMind()
    df = make_ohlcv([10.0] * 80)
    result = pipe.run(
        "AVAH", _signal(), quant={}, df=df,
        exposure=100, allow_new_entries=True, intraday_mode=False,
    )
    assert result.proceed is False
    assert result.stage == "MIND"
    assert "mind evaluation error" in result.reason
