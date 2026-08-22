"""Accumulation/distribution and volume-profile proxies (daily bars, no L2).

Level-2 iceberg detection requires paid feeds; we approximate institutional
footprints with A/D line slope and volume-at-price concentration.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def accumulation_distribution(df):
    """Chaikin A/D line from OHLCV."""
    if df is None or len(df) < 5:
        return None
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    denom = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / denom
    mfm = mfm.fillna(0)
    ad = (mfm * volume).cumsum()
    return ad


def volume_profile_poc(df, bins=20):
    """Point of control: price level with highest volume (histogram proxy)."""
    if df is None or len(df) < 10:
        return None
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].fillna(0)
    if vol.sum() <= 0:
        return float(df["close"].iloc[-1])
    try:
        hist, edges = np.histogram(typical, bins=bins, weights=vol)
        idx = int(hist.argmax())
        return float((edges[idx] + edges[idx + 1]) / 2)
    except Exception:
        return float(df["close"].iloc[-1])


def classify_phase(df, lookback=20):
    """Return ACCUMULATION | DISTRIBUTION | NEUTRAL | UNKNOWN."""
    if df is None or len(df) < lookback + 5:
        return "UNKNOWN", "insufficient data"

    window = df.tail(lookback)
    price_range = window["close"].max() - window["close"].min()
    avg_price = window["close"].mean()
    range_pct = price_range / avg_price * 100 if avg_price else 999

    ad = accumulation_distribution(df)
    if ad is None or len(ad) < lookback:
        return "UNKNOWN", "no A/D"

    ad_slope = float(ad.iloc[-1] - ad.iloc[-lookback])
    price_change = float(window["close"].iloc[-1] - window["close"].iloc[0])

    # Sideways + rising A/D → accumulation; sideways + falling A/D → distribution
    if range_pct < 8:
        if ad_slope > 0 and price_change >= -avg_price * 0.02:
            return "ACCUMULATION", f"A/D 上升 {ad_slope:.0f}，價格橫行 {range_pct:.1f}%"
        if ad_slope < 0 and price_change <= avg_price * 0.02:
            return "DISTRIBUTION", f"A/D 下降 {ad_slope:.0f}，價格橫行 {range_pct:.1f}%"

    if ad_slope > 0 and price_change > 0:
        return "ACCUMULATION", "量價齊升"
    if ad_slope < 0 and price_change < 0:
        return "DISTRIBUTION", "量價齊跌"

    return "NEUTRAL", f"range {range_pct:.1f}%, A/D slope {ad_slope:.0f}"


class MarketStructure:
    DEFAULTS = {
        "enabled": True,
        "block_distribution_entries": True,
        "prefer_accumulation": True,
        "poc_tolerance_pct": 3.0,
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}

    def analyze(self, df):
        phase, detail = classify_phase(df)
        poc = volume_profile_poc(df)
        last = float(df["close"].iloc[-1]) if df is not None and len(df) else None
        poc_dist = abs(last - poc) / poc * 100 if poc and last else None

        return {
            "phase": phase,
            "detail": detail,
            "poc": round(poc, 2) if poc else None,
            "poc_distance_pct": round(poc_dist, 2) if poc_dist is not None else None,
        }

    def allow_long_entry(self, df):
        if not self.cfg.get("enabled", True):
            return True, "structure check off"
        info = self.analyze(df)
        if info["phase"] == "DISTRIBUTION" and self.cfg.get("block_distribution_entries"):
            return False, f"派貨階段: {info['detail']}"
        if info["phase"] == "ACCUMULATION":
            return True, f"吸籌: {info['detail']}"
        return True, info["detail"]
