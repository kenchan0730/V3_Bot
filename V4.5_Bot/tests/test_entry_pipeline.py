"""Unit tests for core.entry_pipeline — per-stage buy path."""

import pytest

from core.entry_pipeline import EntryPipeline, EntryResult
from core.professional_mind import MindDecision, ProfessionalMind
from core.risk_manager import RiskManager
from tests.helpers import make_ohlcv


class _FakePortfolio:
    max_gross_exposure_pct = 60.0

    def __init__(self, correlation_scale=1.0, can_open=True, reason="OK"):
        self._correlation_scale = correlation_scale
        self._can_open = can_open
        self._reason = reason
        self.positions = {}

    def correlation_scale(self, symbol, returns_cache):
        return self._correlation_scale

    def can_open(self, symbol, cost, total_capital, stop_risk, max_gross_pct_override=None):
        if self._can_open:
            return True, "OK"
        return False, self._reason


class _FakeIntraday:
    def __init__(self, enabled=True, result=None):
        self.cfg = {"enabled": enabled}
        self._result = result or {"ok": True, "reason": "vwap ok", "entry_price": 10.02, "metrics": {"vwap": 10.0}}

    def evaluate_entry(self, symbol, action, entry, df=None):
        return dict(self._result)


@pytest.fixture
def pipeline():
    return EntryPipeline(
        RiskManager(initial_capital=1000.0, config={"max_risk_percent": 2.0}),
        _FakePortfolio(),
        ProfessionalMind({"enabled": False, "log_every_deliberation": False}),
        _FakeIntraday(),
        slippage_ticks=1,
        tick_size=0.01,
        price_limit=40.0,
        max_shares=20,
    )


def test_step_slippage(pipeline):
    assert pipeline.step_slippage(10.0) == 10.01


def test_step_intraday_skipped_when_mode_off(pipeline):
    check, entry, rejection = pipeline.step_intraday(
        "AVAH", {"action": "STRONG_BUY"}, 10.0,
        intraday_mode=False, allow_intraday=True, current_regime="NEUTRAL",
    )
    assert rejection is None
    assert check["reason"] == "intraday skipped"
    assert entry == 10.0


def test_step_intraday_rejects_regime_block(pipeline):
    check, entry, rejection = pipeline.step_intraday(
        "AVAH", {"action": "STRONG_BUY"}, 10.0,
        intraday_mode=True, allow_intraday=False, current_regime="RISK_OFF",
    )
    assert rejection == ("regime RISK_OFF blocks intraday", "REGIME")
    assert entry == 10.0


def test_step_intraday_rejects_failed_check(pipeline):
    pipeline.intraday = _FakeIntraday(result={"ok": False, "reason": "too far from vwap"})
    check, entry, rejection = pipeline.step_intraday(
        "AVAH", {"action": "STRONG_BUY"}, 10.0,
        intraday_mode=True, allow_intraday=True, current_regime="NEUTRAL",
    )
    assert rejection == ("too far from vwap", "INTRADAY")
    assert check["ok"] is False


def test_step_intraday_updates_entry_on_pass(pipeline):
    pipeline.intraday = _FakeIntraday(result={
        "ok": True, "reason": "vwap ok", "entry_price": 10.05, "metrics": {"vwap": 10.0},
    })
    check, entry, rejection = pipeline.step_intraday(
        "AVAH", {"action": "STRONG_BUY"}, 10.0,
        intraday_mode=True, allow_intraday=True, current_regime="NEUTRAL",
    )
    assert rejection is None
    assert entry == 10.05


def test_step_sizing_applies_exposure_and_correlation(pipeline):
    pipeline.portfolio = _FakePortfolio(correlation_scale=0.5)
    shares = pipeline.step_sizing(10.0, 9.0, exposure=50, symbol="AVAH", returns_cache={})
    # 2% of 1000 = $20 risk / $1 per share = 20, *50% exposure = 10, *0.5 corr = 5
    assert shares == 5


def test_step_apply_mind_decision_scales_stop_and_shares(pipeline):
    decision = MindDecision(
        stop_override=8.5,
        shares_scale=0.5,
        risk_multiplier=0.5,
    )
    stop, shares = pipeline.step_apply_mind_decision(decision, stop=9.0, shares=10)
    assert stop == 8.5
    assert shares == 2


def test_step_conviction_rejects_low_score(pipeline):
    pipeline.professional = ProfessionalMind({
        "enabled": True,
        "log_every_deliberation": False,
        "conviction_sizing": {"enabled": True, "reject_below": 4},
    })
    shares, conviction, reason = pipeline.step_conviction(
        MindDecision(execution_score=3), shares=10,
    )
    assert conviction == 0.0
    assert reason is not None
    assert shares == 10


def test_step_conviction_scales_reduced_score(pipeline):
    pipeline.professional = ProfessionalMind({
        "enabled": True,
        "log_every_deliberation": False,
    })
    shares, conviction, reason = pipeline.step_conviction(
        MindDecision(execution_score=7), shares=10,
    )
    assert conviction == pytest.approx(0.75)
    assert reason is None
    assert shares == 7


def test_step_validate_pre_trade_rejects_zero_shares(pipeline):
    ok, reason = pipeline.step_validate_pre_trade("AVAH", 0, 10.0, 9.0)
    assert ok is False
    assert "股數" in reason


def test_step_validate_pre_trade_rejects_insufficient_buying_power(pipeline):
    class _FakeIBKR:
        def is_connected(self):
            return True

        def get_buying_power(self):
            return 5.0

    pipeline.auto_trade = True
    pipeline.ibkr = _FakeIBKR()
    ok, reason = pipeline.step_validate_pre_trade("AVAH", 5, 10.0, 9.0)
    assert ok is False
    assert "購買力不足" in reason


def test_run_proceeds_when_all_stages_pass(monkeypatch, pipeline):
    monkeypatch.setattr(
        pipeline.professional,
        "approve_entry",
        lambda *a, **k: MindDecision(approve=True, execution_score=9),
    )
    signal = {"entry": 10.0, "stop": 9.0, "target1": 12.0, "action": "STRONG_BUY"}
    result = pipeline.run("AVAH", signal, quant={}, df=make_ohlcv([10.0] * 80))
    assert isinstance(result, EntryResult)
    assert result.proceed is True
    assert result.stage == "OK"
    assert result.entry == 10.01
    assert result.shares > 0


def test_run_stops_at_mind_rejection(monkeypatch, pipeline):
    pipeline.professional = ProfessionalMind({
        "enabled": True,
        "log_every_deliberation": False,
    })
    monkeypatch.setattr(
        pipeline.professional,
        "approve_entry",
        lambda *a, **k: MindDecision(approve=False, reasons=["liquidity blocked"]),
    )
    signal = {"entry": 10.0, "stop": 9.0, "target1": 12.0, "action": "STRONG_BUY"}
    result = pipeline.run("AVAH", signal, quant={}, df=make_ohlcv([10.0] * 80))
    assert result.proceed is False
    assert result.stage == "MIND"
    assert "liquidity blocked" in result.reason


def test_run_stops_at_pre_trade_validation(monkeypatch, pipeline):
    pipeline.portfolio = _FakePortfolio(can_open=False, reason="gross exposure cap")
    monkeypatch.setattr(
        pipeline.professional,
        "approve_entry",
        lambda *a, **k: MindDecision(approve=True, execution_score=9),
    )
    signal = {"entry": 10.0, "stop": 9.0, "target1": 12.0, "action": "STRONG_BUY"}
    result = pipeline.run("AVAH", signal, quant={}, df=make_ohlcv([10.0] * 80))
    assert result.proceed is False
    assert result.stage == "PRE_TRADE"
    assert result.reason == "gross exposure cap"


# ----- stop override must not silently destroy the R multiple -----

def test_rescale_target_preserves_r_multiple():
    # 1.5R trade whose stop is widened from -1.00 to -2.00 keeps 1.5R.
    assert EntryPipeline.rescale_target(10.0, 9.0, 11.5, 8.0) == pytest.approx(13.0)


def test_rescale_target_is_a_no_op_without_a_change():
    assert EntryPipeline.rescale_target(10.0, 9.0, 11.5, 9.0) == 11.5
    assert EntryPipeline.rescale_target(10.0, 9.0, None, 8.0) is None
    assert EntryPipeline.rescale_target(10.0, 10.0, 11.5, 8.0) == 11.5


def test_run_rescales_target_after_atr_stop_override(monkeypatch, pipeline):
    pipeline.professional.cfg["enabled"] = True
    monkeypatch.setattr(
        pipeline.professional,
        "approve_entry",
        lambda *a, **k: MindDecision(approve=True, execution_score=9, stop_override=8.0),
    )
    signal = {"entry": 10.0, "stop": 9.0, "target1": 11.5, "action": "STRONG_BUY"}
    result = pipeline.run("AVAH", signal, quant={}, df=make_ohlcv([10.0] * 80))
    assert result.stop == 8.0
    # Original geometry was 1.5R; a 2.00 stop distance must target 13.01.
    assert result.target == pytest.approx(result.entry + (result.entry - 8.0) * 1.5, abs=0.05)


# ----- an uneconomic position is skipped, not taken small -----

def test_min_notional_blocks_a_position_too_small_to_pay_its_commission():
    pipe = EntryPipeline(
        RiskManager(initial_capital=1000.0, config={"max_risk_percent": 2.0}),
        _FakePortfolio(),
        ProfessionalMind({"enabled": False, "log_every_deliberation": False}),
        _FakeIntraday(),
        price_limit=40.0,
        max_shares=20,
        min_notional=500.0,
    )
    ok, reason = pipe.step_validate_pre_trade("AVAH", 10, 10.0, 9.0)
    assert ok is False
    assert "最低經濟規模" in reason


def test_min_notional_allows_a_full_size_position():
    pipe = EntryPipeline(
        RiskManager(initial_capital=1000.0, config={"max_risk_percent": 2.0}),
        _FakePortfolio(),
        ProfessionalMind({"enabled": False, "log_every_deliberation": False}),
        _FakeIntraday(),
        price_limit=40.0,
        max_shares=100,
        min_notional=200.0,
    )
    ok, reason = pipe.step_validate_pre_trade("AVAH", 30, 10.0, 9.0)
    assert ok is True and reason == "OK"
