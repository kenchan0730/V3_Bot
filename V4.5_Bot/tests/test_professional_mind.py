"""Tests for professional mind deliberation."""

import pandas as pd
import pytest

from core.professional_mind import ProfessionalMind
from core.regime import RegimeResult, RISK_OFF
from core.strategies.base import MarketContext
from tests.helpers import make_ohlcv


@pytest.fixture
def mind():
    return ProfessionalMind({
        "enabled": True,
        "strategic_cash_enabled": True,
        "log_every_deliberation": False,
        "market_structure": {"enabled": True, "block_distribution_entries": True},
        "liquidity": {"enabled": True, "avoid_first_minutes": 0, "avoid_last_minutes": 0},
        "pdt": {"enabled": True, "min_equity": 25000},
    })


@pytest.fixture
def df():
    closes = [10 + i * 0.05 for i in range(80)]
    return make_ohlcv(closes)


def test_strategic_cash_on_risk_off(mind):
    regime = RegimeResult(regime=RISK_OFF, score=30, exposure_pct=25, allow_new_entries=False)
    decision = mind.deliberate_cycle(regime, _FakePortfolio(), 1000, watchlist_len=5)
    assert decision.action == "STRATEGIC_CASH"
    assert mind.strategic_cash_mode is True


def test_rejects_distribution_phase(mind, df, monkeypatch):
    monkeypatch.setattr(
        "core.market_structure.classify_phase",
        lambda d, lookback=20: ("DISTRIBUTION", "test distribution"),
    )
    ctx = MarketContext("AVAH", 12.0, allow_new_entries=True, regime="NEUTRAL")
    signal = {"action": "STRONG_BUY", "confidence": 0.7}
    decision = mind.approve_entry(
        "AVAH", signal, df, ctx, _FakePortfolio(), _FakeRisk(), 12.0, 11.0, 5,
    )
    assert decision.approve is False


def test_approves_neutral_structure(mind, df, monkeypatch):
    monkeypatch.setattr(
        "core.market_structure.classify_phase",
        lambda d, lookback=20: ("ACCUMULATION", "sideways accumulation"),
    )
    monkeypatch.setattr(
        "core.economic_calendar.EconomicCalendar.current_context",
        lambda self, now=None: {"active": False, "risk_multiplier": 1.0, "events": []},
    )
    ctx = MarketContext("AVAH", 12.0, allow_new_entries=True, regime="NEUTRAL")
    signal = {"action": "STRONG_BUY", "confidence": 0.8}
    decision = mind.approve_entry(
        "AVAH", signal, df, ctx, _FakePortfolio(), _FakeRisk(), 12.0, 11.0, 5,
    )
    assert decision.approve is True
    assert decision.execution_score >= 7


class _FakePortfolio:
    positions = {}

    def has_position(self, symbol):
        return False

    def gross_exposure(self):
        return 0.0


class _FakeRisk:
    total_capital = 1000
