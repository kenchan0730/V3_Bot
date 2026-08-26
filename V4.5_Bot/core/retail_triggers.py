"""Alternative entry triggers a discretionary swing trader actually uses.

The original signal required a textbook bullish candlestick on the entry bar.
Across a two-year replay that single requirement accounted for most of the
rejected days: 296 of 476 no-signal bars were missing only the candle edge,
while trend, volume and volatility all agreed.

A trigger is still mandatory — this module just widens what counts as one:

    pullback_hold  price pulls back into MA20, holds it, closes green
    breakout       close clears the recent range high on expanding volume
    higher_low     three rising lows above MA20 (continuation)

Each trigger supplies its own entry and stop so the downstream risk math is
unchanged. Nothing here loosens the trend, volume, volatility or z-score edges.
"""

from __future__ import annotations

import logging

from core.position_sizer import compute_atr

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": True,
    "pullback_enabled": True,
    "pullback_ma": 20,
    "pullback_max_distance_pct": 3.5,
    "pullback_strength": 0.45,
    "breakout_enabled": True,
    "breakout_lookback": 20,
    "breakout_min_vol_ratio": 1.2,
    "breakout_strength": 0.60,
    "higher_low_enabled": True,
    "higher_low_strength": 0.40,
    "stop_atr_multiplier": 1.5,
    "stop_pct_fallback": 3.0,
    "tick": 0.01,
}


def _stop_price(df, close, cfg, floor=None):
    """ATR stop, tightened to a structural low when one is nearby."""
    atr = compute_atr(df, period=14)
    if atr and atr > 0:
        stop = close - atr * float(cfg["stop_atr_multiplier"])
    else:
        stop = close * (1 - float(cfg["stop_pct_fallback"]) / 100.0)
    if floor is not None and floor < close:
        stop = max(stop, floor * 0.99)
    return round(min(stop, close - float(cfg["tick"])), 2)


def _pullback_hold(df, cfg, ma20, ma50):
    if not cfg.get("pullback_enabled", True) or not ma20 or not ma50:
        return None
    bar = df.iloc[-1]
    close, open_, low = float(bar["close"]), float(bar["open"]), float(bar["low"])
    if close <= ma50 or close <= open_:
        return None
    distance = abs(close - ma20) / ma20 * 100.0
    if distance > float(cfg["pullback_max_distance_pct"]):
        return None
    # The bar must have actually visited the average, not merely floated above it.
    if low > ma20 * 1.02:
        return None
    return {
        "name": "pullback_hold",
        "strength": float(cfg["pullback_strength"]),
        "entry": round(close + float(cfg["tick"]), 2),
        "stop": _stop_price(df, close, cfg, floor=min(low, ma20)),
        "detail": f"回測 MA20 距離 {distance:.1f}% 並收紅",
    }


def _breakout(df, cfg, vol_ratio):
    if not cfg.get("breakout_enabled", True):
        return None
    lookback = int(cfg["breakout_lookback"])
    if len(df) < lookback + 2:
        return None
    if vol_ratio is not None and float(vol_ratio) < float(cfg["breakout_min_vol_ratio"]):
        return None
    window = df["close"].iloc[-(lookback + 1):-1]
    prior_high = float(window.max())
    bar = df.iloc[-1]
    close = float(bar["close"])
    if close <= prior_high:
        return None
    return {
        "name": "range_breakout",
        "strength": float(cfg["breakout_strength"]),
        "entry": round(close + float(cfg["tick"]), 2),
        "stop": _stop_price(df, close, cfg, floor=prior_high),
        "detail": f"突破 {lookback} 日高點 {prior_high:.2f}"
        + (f"，量比 {float(vol_ratio):.2f}×" if vol_ratio else ""),
    }


def _higher_low(df, cfg, ma20):
    if not cfg.get("higher_low_enabled", True) or not ma20 or len(df) < 6:
        return None
    lows = [float(v) for v in df["low"].iloc[-3:]]
    if not (lows[0] < lows[1] < lows[2]):
        return None
    bar = df.iloc[-1]
    close = float(bar["close"])
    if close <= ma20 or close <= float(bar["open"]):
        return None
    return {
        "name": "higher_low",
        "strength": float(cfg["higher_low_strength"]),
        "entry": round(close + float(cfg["tick"]), 2),
        "stop": _stop_price(df, close, cfg, floor=lows[0]),
        "detail": "連續三根抬高低點且站穩 MA20",
    }


def detect(df, *, ma20=None, ma50=None, vol_ratio=None, config=None):
    """Strongest available retail trigger, or ``None`` when nothing fires."""
    cfg = {**DEFAULTS, **(config or {})}
    if not cfg.get("enabled", True) or df is None or len(df) < 25:
        return None

    candidates = [
        _breakout(df, cfg, vol_ratio),
        _pullback_hold(df, cfg, ma20, ma50),
        _higher_low(df, cfg, ma20),
    ]
    found = [c for c in candidates if c and c["stop"] < c["entry"]]
    if not found:
        return None
    return max(found, key=lambda c: c["strength"])
