"""Widening a stop must not silently increase dollar risk.

Volatility scaling shrinks share count while an ATR stop can widen risk per
share. Without a budget check the two can cancel out and leave actual dollar
risk above the per-trade limit.
"""

import pytest

from core.position_sizer import DynamicPositionSizer
from core.professional_mind import ProfessionalMind
from core.strategies.base import MarketContext
from tests.helpers import make_ohlcv


@pytest.fixture
def sizer():
    return DynamicPositionSizer({"enabled": True})


def test_within_budget_is_untouched(sizer):
    shares, msg = sizer.enforce_risk_budget(10, 12.0, 11.5, 1275.0, 1.5)
    assert shares == 10
    assert msg == "OK"


def test_widened_stop_is_capped(sizer):
    # 20 shares x $2.00 risk = $40 vs a $19.13 budget (1.5% of $1,275)
    shares, msg = sizer.enforce_risk_budget(20, 12.0, 10.0, 1275.0, 1.5)
    assert shares < 20
    assert shares == int(1275.0 * 0.015 / 2.0)
    assert "風險守恆" in msg


def test_capped_shares_respect_budget(sizer):
    capital, risk_pct = 1275.0, 1.5
    shares, _ = sizer.enforce_risk_budget(50, 20.0, 17.0, capital, risk_pct)
    assert shares * (20.0 - 17.0) <= capital * risk_pct / 100 + 1e-9


def test_zero_or_invalid_inputs_pass_through(sizer):
    assert sizer.enforce_risk_budget(0, 12.0, 11.0, 1275.0, 1.5) == (0, "OK")
    assert sizer.enforce_risk_budget(10, 12.0, 12.0, 1275.0, 1.5) == (10, "OK")
    assert sizer.enforce_risk_budget(10, 12.0, 11.0, 0.0, 1.5) == (10, "OK")


def test_stop_wider_than_budget_rejects_entirely(sizer):
    shares, msg = sizer.enforce_risk_budget(5, 100.0, 50.0, 1275.0, 1.5)
    assert shares == 0
    assert "風險守恆" in msg


class _FakePortfolio:
    positions = {}

    def has_position(self, symbol):
        return False

    def gross_exposure(self):
        return 0.0


class _FakeRisk:
    total_capital = 1275.0
    current_risk_pct = 1.5


def _mind(**sizer_overrides):
    return ProfessionalMind({
        "enabled": True, "log_every_deliberation": False,
        "liquidity": {"enabled": True, "avoid_first_minutes": 0, "avoid_last_minutes": 0},
        "position_sizer": {"use_atr_stop": False, **sizer_overrides},
    })


@pytest.fixture
def patched_context(monkeypatch):
    monkeypatch.setattr(
        "core.market_structure.classify_phase",
        lambda d, lookback=20: ("ACCUMULATION", "test"),
    )
    monkeypatch.setattr(
        "core.economic_calendar.EconomicCalendar.current_context",
        lambda self, now=None: {"active": False, "risk_multiplier": 1.0, "events": []},
    )


def test_mind_rejects_when_budget_leaves_no_shares(patched_context):
    """A stop so wide that even one share breaks the budget must be refused."""
    mind = _mind()
    df = make_ohlcv([100 + i for i in range(80)])
    ctx = MarketContext("AVAH", 150.0, allow_new_entries=True, regime="NEUTRAL")

    decision = mind.approve_entry(
        "AVAH", {"action": "STRONG_BUY", "confidence": 0.8},
        df, ctx, _FakePortfolio(), _FakeRisk(),
        entry_price=150.0, stop_price=100.0, base_shares=5,
    )
    assert decision.approve is False
    assert any("風險守恆" in r for r in decision.reasons)


def test_mind_scales_down_instead_of_rejecting(patched_context):
    mind = _mind()
    df = make_ohlcv([10 + i * 0.05 for i in range(80)])
    ctx = MarketContext("AVAH", 12.0, allow_new_entries=True, regime="NEUTRAL")

    decision = mind.approve_entry(
        "AVAH", {"action": "STRONG_BUY", "confidence": 0.8},
        df, ctx, _FakePortfolio(), _FakeRisk(),
        entry_price=12.0, stop_price=10.0, base_shares=40,
    )
    assert decision.approve is True
    assert decision.shares_scale < 1.0
    final_shares = int(40 * decision.shares_scale)
    assert final_shares * 2.0 <= _FakeRisk.total_capital * 0.015 + 2.0


def test_atr_stop_tightening_keeps_full_size(patched_context):
    """When the ATR stop is tighter than the signal stop, no capping is needed."""
    mind = ProfessionalMind({
        "enabled": True, "log_every_deliberation": False,
        "liquidity": {"enabled": True, "avoid_first_minutes": 0, "avoid_last_minutes": 0},
    })
    df = make_ohlcv([100 + i for i in range(80)])
    ctx = MarketContext("AVAH", 150.0, allow_new_entries=True, regime="NEUTRAL")

    decision = mind.approve_entry(
        "AVAH", {"action": "STRONG_BUY", "confidence": 0.8},
        df, ctx, _FakePortfolio(), _FakeRisk(),
        entry_price=150.0, stop_price=100.0, base_shares=5,
    )
    assert decision.approve is True
    assert decision.stop_override > 100.0
