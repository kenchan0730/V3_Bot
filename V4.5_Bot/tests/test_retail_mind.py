import pandas as pd
import pytest

from core.retail_mind import RetailMind
from core.strategies.base import MarketContext


def make_df(rows=80, close=20.0, volume=1_500_000, spread_pct=2.0):
    half = close * spread_pct / 200.0
    return pd.DataFrame(
        {
            "open": [close] * rows,
            "high": [close + half] * rows,
            "low": [close - half] * rows,
            "close": [close] * rows,
            "volume": [volume] * rows,
        }
    )


def make_context(price=20.0, ma20=19.5, ma50=18.0, vol_ratio=1.3):
    return MarketContext(
        symbol="TEST", price=price, quant={"rsi": 55, "z_score": 0.9},
        vol_ratio=vol_ratio, ma20=ma20, ma50=ma50,
    )


GOOD_SIGNAL = {
    "action": "STRONG_BUY",
    "track": "STRONG",
    "entry": 20.0,
    "stop": 19.0,
    "target1": 22.0,
    "confluence_score": 7,
}


def test_approves_a_clean_affordable_setup():
    verdict = RetailMind().evaluate(
        "TEST", GOOD_SIGNAL, make_context(), df=make_df(),
        capital=5000.0, max_shares=50, max_symbol_pct=100.0,
    )
    assert verdict.approve is True
    assert verdict.verdict == "BUY"
    assert 0 < verdict.size_factor <= 1.0


def test_rejects_when_account_cannot_afford_one_share():
    verdict = RetailMind().evaluate(
        "TEST", {**GOOD_SIGNAL, "entry": 500.0}, make_context(price=500.0),
        df=make_df(close=500.0), capital=100.0, max_shares=20,
    )
    assert verdict.approve is False
    assert "資金不足" in verdict.reasons[0]


def test_rejects_when_commission_drag_dominates():
    """A $60 position paying $2 of round-trip commission is not a trade."""
    verdict = RetailMind().evaluate(
        "TEST", {**GOOD_SIGNAL, "entry": 20.0}, make_context(),
        df=make_df(), capital=60.0, max_shares=3,
    )
    assert verdict.approve is False
    assert "成本拖累" in verdict.reasons[0]


def test_rejects_poor_reward_risk():
    signal = {**GOOD_SIGNAL, "target1": 20.5}
    verdict = RetailMind().evaluate(
        "TEST", signal, make_context(), df=make_df(),
        capital=5000.0, max_shares=50,
    )
    assert verdict.approve is False
    assert "風報比" in verdict.reasons[0]


def test_rejects_price_extended_far_above_ma50():
    verdict = RetailMind().evaluate(
        "TEST", GOOD_SIGNAL, make_context(price=20.0, ma50=13.0), df=make_df(),
        capital=5000.0, max_shares=50,
    )
    assert verdict.approve is False
    assert "MA50" in verdict.reasons[0]


def test_rejects_illiquid_tape():
    verdict = RetailMind().evaluate(
        "TEST", GOOD_SIGNAL, make_context(), df=make_df(volume=5_000),
        capital=5000.0, max_shares=50,
    )
    assert verdict.approve is False
    assert "成交額" in verdict.reasons[0]


def test_unprofitable_name_needs_a_catalyst():
    mind = RetailMind()
    without = mind.evaluate(
        "TEST", GOOD_SIGNAL, make_context(), df=make_df(),
        fundamental_view={"tier": "C"}, capital=5000.0, max_shares=50,
    )
    assert without.approve is False
    assert "催化劑" in without.reasons[0]

    with_news = mind.evaluate(
        "TEST", GOOD_SIGNAL, make_context(), df=make_df(),
        fundamental_view={"tier": "C"},
        news_view={"score": 0.4, "total": 6},
        capital=5000.0, max_shares=50,
    )
    assert with_news.approve is True


def test_external_signal_counts_as_catalyst():
    verdict = RetailMind().evaluate(
        "TEST", GOOD_SIGNAL, make_context(), df=make_df(),
        fundamental_view={"tier": "C"},
        external_signal={"source": "my-app", "note": "big contract"},
        capital=5000.0, max_shares=50,
    )
    assert verdict.approve is True
    assert any("App" in r or "外部訊號" in r for r in verdict.reasons)


def test_micro_cap_tier_d_is_vetoed():
    verdict = RetailMind().evaluate(
        "TEST", GOOD_SIGNAL, make_context(), df=make_df(),
        fundamental_view={"tier": "D"}, capital=5000.0, max_shares=50,
    )
    assert verdict.approve is False


def test_watch_verdict_between_skip_and_buy():
    """A thin-but-legal setup lands on WATCH rather than BUY or SKIP."""
    mind = RetailMind({"min_retail_score": 8, "watch_score_margin": 4})
    weak = {**GOOD_SIGNAL, "confluence_score": 3, "target1": 21.5}
    verdict = mind.evaluate(
        "TEST", weak, make_context(price=20.0, ma20=20.5, ma50=20.2),
        df=make_df(), capital=5000.0, max_shares=50,
    )
    assert verdict.verdict == "WATCH"
    assert verdict.approve is False


def test_size_ladder_scales_with_score():
    mind = RetailMind()
    assert mind._size_from_score(10) == 1.0
    assert mind._size_from_score(8) == 0.75
    assert mind._size_from_score(6) == 0.55
    assert mind._size_from_score(5) == 0.4


def test_breakeven_metric_is_reported():
    verdict = RetailMind().evaluate(
        "TEST", GOOD_SIGNAL, make_context(), df=make_df(),
        capital=5000.0, max_shares=50,
    )
    assert verdict.metrics["breakeven_move_pct"] > 0
    assert verdict.metrics["shares"] > 0


def test_disabled_mind_approves_without_scoring():
    verdict = RetailMind({"enabled": False}).evaluate(
        "TEST", GOOD_SIGNAL, make_context(), df=make_df(), capital=0.0,
    )
    assert verdict.approve is True
