"""Integration: real TradingSignals output must not crash ProfessionalMind."""

import pytest

from core.professional_mind import ProfessionalMind
from core.strategies.base import MarketContext
from core.trading_signals import TradingSignals
from tests.helpers import make_ohlcv
from tests.test_trading_signals import levels, with_hammer, _make_df


@pytest.fixture
def mind():
    return ProfessionalMind({
        "enabled": True,
        "strategic_cash_enabled": False,
        "log_every_deliberation": False,
        "market_structure": {"enabled": True, "block_distribution_entries": True},
        "liquidity": {"enabled": True, "avoid_first_minutes": 0, "avoid_last_minutes": 0},
        "pdt": {"enabled": True, "min_equity": 25000},
    })


class _FakePortfolio:
    positions = {}

    def has_position(self, symbol):
        return False

    def gross_exposure(self):
        return 0.0


class _FakeRisk:
    total_capital = 1275.0


def test_strong_buy_signal_does_not_crash_professional_mind(mind, monkeypatch):
    """Regression: float('HIGH') used to raise and block every live buy."""
    monkeypatch.setattr(
        "core.market_structure.classify_phase",
        lambda d, lookback=20: ("ACCUMULATION", "test accumulation"),
    )
    monkeypatch.setattr(
        "core.economic_calendar.EconomicCalendar.current_context",
        lambda self, now=None: {"active": False, "risk_multiplier": 1.0, "events": []},
    )

    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 1.0, 1.6, ma20, ma50, zscore_min=0.5)

    assert signal["action"] == "STRONG_BUY"

    ctx = MarketContext("AVAH", signal["entry"], allow_new_entries=True, regime="NEUTRAL")
    decision = mind.approve_entry(
        "AVAH",
        signal,
        df,
        ctx,
        _FakePortfolio(),
        _FakeRisk(),
        signal["entry"],
        signal["stop"],
        5,
    )

    assert decision.execution_score >= 8
    assert decision.approve is True


def test_legacy_string_confidence_still_parses(mind, monkeypatch):
    """Older payloads (and archived journals) may still carry "HIGH"."""
    monkeypatch.setattr(
        "core.market_structure.classify_phase",
        lambda d, lookback=20: ("ACCUMULATION", "test accumulation"),
    )
    monkeypatch.setattr(
        "core.economic_calendar.EconomicCalendar.current_context",
        lambda self, now=None: {"active": False, "risk_multiplier": 1.0, "events": []},
    )
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    legacy = {"action": "STRONG_BUY", "confidence": "HIGH", "entry": 12.0, "stop": 11.0}
    ctx = MarketContext("AVAH", 12.0, allow_new_entries=True, regime="NEUTRAL")

    decision = mind.approve_entry(
        "AVAH", legacy, df, ctx, _FakePortfolio(), _FakeRisk(), 12.0, 11.0, 5,
    )
    assert decision.approve is True


def test_confluence_score_drives_execution_score(mind, monkeypatch):
    monkeypatch.setattr(
        "core.market_structure.classify_phase",
        lambda d, lookback=20: ("NEUTRAL", "sideways"),
    )
    monkeypatch.setattr(
        "core.economic_calendar.EconomicCalendar.current_context",
        lambda self, now=None: {"active": False, "risk_multiplier": 1.0, "events": []},
    )
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    ctx = MarketContext("AVAH", 12.0, allow_new_entries=True, regime="NEUTRAL")

    weak = mind.approve_entry(
        "AVAH", {"action": "STRONG_BUY", "confidence": 0.55, "confluence_score": 5},
        df, ctx, _FakePortfolio(), _FakeRisk(), 12.0, 11.0, 5,
    )
    strong = mind.approve_entry(
        "AVAH", {"action": "STRONG_BUY", "confidence": 0.9, "confluence_score": 10},
        df, ctx, _FakePortfolio(), _FakeRisk(), 12.0, 11.0, 5,
    )
    assert strong.execution_score > weak.execution_score
