from unittest.mock import MagicMock

import pytest

from core.swing_filters import SwingQualityFilter
from core.strategies.base import MarketContext
from core.trading_signals import TradingSignals
from tests.test_trading_signals import _make_df, levels, with_hammer


def test_moderate_buy_when_four_edges_pass():
    df = with_hammer(_make_df([10 + i * 0.08 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(
        df, price, 18.0, 0.9, 1.3, ma20, ma50,
        zscore_min=0.5, min_candle_strength=0.3,
        min_vol_ratio_high=1.2, trend_mode="swing",
        moderate_enabled=True, moderate_min_edges=4, moderate_min_confluence=5,
    )
    assert signal["action"] in ("STRONG_BUY", "MODERATE_BUY", "HOLD")


def test_swing_filter_rejects_low_confluence():
    filt = SwingQualityFilter({"enabled": True, "strong_min_confluence": 6})
    ctx = MarketContext(
        symbol="INTC", price=30, quant={"rsi": 55, "z_score": 0.9},
        vol_ratio=1.4, breadth_score=50,
    )
    signal = {"action": "STRONG_BUY", "track": "STRONG", "confluence_score": 4}
    ok, reason = filt.validate("INTC", signal, ctx)
    assert ok is False
    assert "共振" in reason


def test_swing_filter_rejects_overbought_rsi():
    filt = SwingQualityFilter({"enabled": True, "reject_rsi_above": 72})
    ctx = MarketContext(
        symbol="INTC", price=30, quant={"rsi": 78, "z_score": 0.9},
        vol_ratio=1.5, breadth_score=50,
    )
    signal = {"action": "STRONG_BUY", "track": "STRONG", "confluence_score": 7}
    filt.portfolio = MagicMock()
    filt.portfolio.sector_of.return_value = "Technology"
    filt._sector_cache = {
        "leading_sectors": ["Technology", "Energy"],
        "relative_strength": {"Technology": 2.0},
    }
    ok, reason = filt.validate("INTC", signal, ctx)
    assert ok is False
    assert "RSI" in reason


def test_swing_filter_accepts_leading_sector():
    filt = SwingQualityFilter({"enabled": True, "strong_min_confluence": 5})
    ctx = MarketContext(
        symbol="INTC", price=30, quant={"rsi": 55, "z_score": 0.9},
        vol_ratio=1.5, breadth_score=50,
    )
    signal = {"action": "MODERATE_BUY", "track": "MODERATE", "confluence_score": 6}
    filt.portfolio = MagicMock()
    filt.portfolio.sector_of.return_value = "Technology"
    filt._sector_cache = {
        "leading_sectors": ["Technology", "Healthcare"],
        "relative_strength": {"Technology": 1.5},
    }
    ok, reason = filt.validate("INTC", signal, ctx)
    assert ok is True
