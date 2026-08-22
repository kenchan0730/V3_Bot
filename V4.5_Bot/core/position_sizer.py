"""ATR-based stops and fractional-Kelly position sizing.

Professional retail practice: size by volatility (ATR), not fixed ticks;
use 1/4 Kelly cap so risk-of-ruin stays near zero.
"""

import logging
import math

import pandas as pd

logger = logging.getLogger(__name__)


def compute_atr(df, period=14):
    """Average True Range on a lowercase OHLCV frame."""
    if df is None or len(df) < period + 1:
        return None
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if atr == atr else None


def atr_stop_price(entry, atr, side="long", multiplier=2.0):
    if atr is None or atr <= 0:
        return None
    if side == "long":
        return round(entry - atr * multiplier, 2)
    return round(entry + atr * multiplier, 2)


def fractional_kelly_shares(
    win_rate, avg_win, avg_loss, entry_price, total_capital,
    fraction=0.25, max_pct=0.5,
):
    """Kelly fraction capped at ``fraction`` (default quarter-Kelly) of capital."""
    if entry_price <= 0 or total_capital <= 0:
        return 0
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0
    b = avg_win / avg_loss
    kelly = win_rate - (1 - win_rate) / b
    if kelly <= 0:
        return 0
    kelly = min(kelly * fraction, max_pct)
    dollars = total_capital * kelly
    return max(0, int(dollars / entry_price))


def risk_of_ruin_approx(win_rate, payoff_ratio, risk_per_trade_pct):
    """Simplified gambler's ruin probability (0–1). Lower is better."""
    if win_rate <= 0 or win_rate >= 1 or payoff_ratio <= 0 or risk_per_trade_pct <= 0:
        return 1.0
    q = 1 - win_rate
    edge = win_rate * payoff_ratio - q
    if edge <= 0:
        return 1.0
    try:
        units = 100.0 / risk_per_trade_pct
        ratio = (q / win_rate) * (1.0 / payoff_ratio)
        if ratio >= 1:
            return 1.0
        return float(ratio ** units)
    except (OverflowError, ValueError):
        return 0.0


class DynamicPositionSizer:
    DEFAULTS = {
        "enabled": True,
        "atr_period": 14,
        "atr_multiplier": 2.0,
        "use_atr_stop": True,
        "kelly_enabled": False,
        "kelly_fraction": 0.25,
        "kelly_win_rate": 0.45,
        "kelly_avg_win": 1.5,
        "kelly_avg_loss": 1.0,
        "vix_scale_threshold": 25.0,
        "vix_scale_factor": 0.7,
        "max_risk_of_ruin": 0.05,
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}

    def suggest_stop(self, df, entry, signal_stop=None):
        if not self.cfg.get("use_atr_stop", True):
            return signal_stop
        atr = compute_atr(df, int(self.cfg.get("atr_period", 14)))
        atr_stop = atr_stop_price(entry, atr, multiplier=float(self.cfg.get("atr_multiplier", 2.0)))
        if atr_stop is None:
            return signal_stop
        if signal_stop and signal_stop > 0:
            return max(atr_stop, signal_stop) if atr_stop < entry else signal_stop
        return atr_stop

    def scale_shares(self, base_shares, df, entry, stop, total_capital, vix=18.0):
        shares = int(base_shares)
        if shares <= 0:
            return 0, "zero base"

        atr = compute_atr(df, int(self.cfg.get("atr_period", 14)))
        reasons = []

        if atr and entry > 0:
            atr_pct = atr / entry * 100
            if atr_pct > 5:
                shares = int(shares * 0.7)
                reasons.append(f"高波動 ATR {atr_pct:.1f}% 縮倉")
            elif atr_pct > 3:
                shares = int(shares * 0.85)
                reasons.append(f"中波動 ATR {atr_pct:.1f}% 微縮")

        if vix > float(self.cfg.get("vix_scale_threshold", 25)):
            factor = float(self.cfg.get("vix_scale_factor", 0.7))
            shares = int(shares * factor)
            reasons.append(f"VIX {vix:.1f} 縮倉 x{factor}")

        if self.cfg.get("kelly_enabled"):
            kelly_sh = fractional_kelly_shares(
                float(self.cfg.get("kelly_win_rate", 0.45)),
                float(self.cfg.get("kelly_avg_win", 1.5)),
                float(self.cfg.get("kelly_avg_loss", 1.0)),
                entry, total_capital,
                fraction=float(self.cfg.get("kelly_fraction", 0.25)),
            )
            if kelly_sh > 0 and kelly_sh < shares:
                shares = kelly_sh
                reasons.append(f"1/4 Kelly 上限 {kelly_sh} 股")

        if stop and entry > stop and total_capital > 0:
            risk_pct = (entry - stop) / entry * (shares * entry / total_capital) * 100
            ruin = risk_of_ruin_approx(
                float(self.cfg.get("kelly_win_rate", 0.45)),
                float(self.cfg.get("kelly_avg_win", 1.5)) / float(self.cfg.get("kelly_avg_loss", 1.0)),
                max(risk_pct, 0.01),
            )
            max_ruin = float(self.cfg.get("max_risk_of_ruin", 0.05))
            if ruin > max_ruin:
                shares = int(shares * 0.5)
                reasons.append(f"破產風險 {ruin:.2%} > {max_ruin:.0%} 再縮倉")

        return max(0, shares), "; ".join(reasons) if reasons else "OK"
