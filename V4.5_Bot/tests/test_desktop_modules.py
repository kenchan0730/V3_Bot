"""Tests for V4.5 Desktop intelligence modules."""

from core.desktop_intelligence import DesktopIntelligence
from core.insider_tracker import InsiderTracker, InsiderTransaction
from core.earnings_calendar import EarningsCalendar


def test_score_label_mapping():
    intel = DesktopIntelligence()
    assert intel._score_label(9.5) == "強烈看漲"
    assert intel._score_label(2) == "強烈看跌"
    assert intel._score_label(5) == "中性"


def test_sentiment_to_score_bounds():
    intel = DesktopIntelligence()
    assert intel._sentiment_to_score(-1, 5) >= 1
    assert intel._sentiment_to_score(1, 5) <= 10


def test_insider_high_conviction():
    tracker = InsiderTracker()
    tx = InsiderTransaction(
        symbol="TEST",
        name="John",
        title="CEO",
        transaction_date="2026-01-01",
        transaction_code="P",
        price=10,
        shares=100,
        value=1000,
        change=30,
    )
    assert tracker._is_high_conviction(tx)


def test_insider_rank():
    tracker = InsiderTracker()
    txs = [
        InsiderTransaction("A", "X", "CEO", "2026-01-01", "P", 10, 1000, 10000, 30),
        InsiderTransaction("B", "Y", "CFO", "2026-01-01", "S", 5, 100, 500, -10),
    ]
    ranked = tracker.rank_transactions(txs)
    assert len(ranked) == 2
    assert ranked[0]["side"] == "buy"


def test_earnings_score_label():
    cal = EarningsCalendar()
    assert cal._score_label(9) == "強烈看漲"
    assert cal._score_label(1) == "強烈看跌"
