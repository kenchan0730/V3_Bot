"""Intraday execution layer without paid data vendors.

Primary source: IBKR 1/5-minute bars (real-time when TWS/Gateway connected).
Fallback: yfinance intraday (delayed ~15 min) for signal validation only.

Supports:
- Session VWAP and distance checks
- Opening-range breakout / pullback confirmation
- Limit entry adjustment near VWAP
"""

import logging
from datetime import datetime, time as dt_time

import pandas as pd
import pytz

from core.data_utils import intraday_quality_report
from core.market_data_sources import fetch_intraday_bars

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


class IntradayEngine:
    DEFAULTS = {
        "enabled": True,
        "bar_size": "5 mins",
        "fallback_interval": "5m",
        "opening_range_minutes": 30,
        "vwap_pullback_pct": 0.8,
        "max_distance_from_vwap_pct": 1.5,
        "min_intraday_bars": 12,
        "require_above_vwap": False,
        "allow_opening_range_breakout": True,
        "session_start": "09:30",
        "session_end": "16:00",
        "skip_first_minutes": 5,
        "skip_last_minutes": 10,
        "max_bar_move_pct": 10.0,
        "fetch_timeout_seconds": 20,
    }

    def __init__(self, config=None, ibkr=None, market_data_config=None):
        cfg = {**self.DEFAULTS, **(config or {})}
        self.cfg = cfg
        self.ibkr = ibkr
        self.market_data_config = market_data_config or {}

    def fetch_bars(self, symbol):
        """Return today's intraday OHLCV (lowercase columns, DatetimeIndex ET)."""
        merged_cfg = {
            **self.market_data_config,
            "bar_size": self.cfg["bar_size"],
            "fallback_interval": self.cfg["fallback_interval"],
            "min_intraday_bars": self.cfg["min_intraday_bars"],
            "fetch_timeout_seconds": self.cfg.get("fetch_timeout_seconds", 20),
        }
        df, source = fetch_intraday_bars(symbol, ibkr=self.ibkr, config=merged_cfg)
        if df is None or df.empty:
            return None
        self._last_source = source
        return df

    def quality_gate(self, df):
        """Apply the daily-equivalent quality checks to intraday bars."""
        return intraday_quality_report(
            df,
            min_bars=int(self.cfg.get("min_intraday_bars", 12)),
            max_bar_move_pct=float(self.cfg.get("max_bar_move_pct", 10.0)),
        )

    @staticmethod
    def compute_vwap(df):
        if df is None or df.empty:
            return None
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        vol = df["volume"].replace(0, pd.NA).fillna(1.0)
        cum_vol = vol.cumsum()
        cum_pv = (typical * vol).cumsum()
        vwap = cum_pv / cum_vol
        return vwap

    def opening_range(self, df):
        """High/low of the first N minutes after the open."""
        if df is None or df.empty:
            return None
        minutes = int(self.cfg["opening_range_minutes"])
        start = df.index.min()
        cutoff = start + pd.Timedelta(minutes=minutes)
        window = df[df.index <= cutoff]
        if window.empty:
            window = df.head(max(1, minutes // 5))
        return {
            "high": float(window["high"].max()),
            "low": float(window["low"].min()),
            "minutes": minutes,
        }

    def in_trade_window(self, now=None):
        now = now or datetime.now(ET)
        if now.weekday() >= 5:
            return False, "weekend"
        start_h, start_m = map(int, self.cfg["session_start"].split(":"))
        end_h, end_m = map(int, self.cfg["session_end"].split(":"))
        open_t = dt_time(start_h, start_m)
        close_t = dt_time(end_h, end_m)
        t = now.time()
        if t < open_t or t > close_t:
            return False, "outside session"
        skip_open = open_t.hour * 60 + open_t.minute + int(self.cfg["skip_first_minutes"])
        skip_close = close_t.hour * 60 + close_t.minute - int(self.cfg["skip_last_minutes"])
        now_min = t.hour * 60 + t.minute
        if now_min < skip_open:
            return False, "opening buffer"
        if now_min > skip_close:
            return False, "closing buffer"
        return True, "OK"

    def evaluate_entry(self, symbol, daily_action, proposed_entry, df=None):
        """Gate a daily STRONG_BUY with intraday confirmation.

        Returns dict: ok, reason, entry_price, vwap, opening_range, source, metrics
        """
        if not self.cfg.get("enabled", True):
            return self._pass(proposed_entry, "intraday disabled")

        if daily_action not in ("STRONG_BUY", "BUY"):
            return self._pass(proposed_entry, "not a buy")

        ok_window, window_reason = self.in_trade_window()
        if not ok_window:
            return {"ok": False, "reason": f"intraday window: {window_reason}",
                    "entry_price": proposed_entry, "metrics": {}}

        df = df if df is not None else self.fetch_bars(symbol)
        if df is None or df.empty:
            return {"ok": False, "reason": "no intraday bars",
                    "entry_price": proposed_entry, "metrics": {}}

        quality = self.quality_gate(df)
        if not quality["ok"]:
            logger.warning(f"{symbol} 盤中數據品質不合格: {quality['message']}")
            return {"ok": False, "reason": f"intraday data [{quality['stage']}]: {quality['message']}",
                    "entry_price": proposed_entry, "metrics": {"quality": quality}}

        vwap_series = self.compute_vwap(df)
        vwap = float(vwap_series.iloc[-1])
        last_close = float(df["close"].iloc[-1])
        dist_pct = abs(last_close - vwap) / vwap * 100.0 if vwap else 0.0

        orb = self.opening_range(df)
        source = getattr(self, "_last_source", None)
        if not source:
            source = "ibkr" if self.ibkr and self.ibkr.is_connected() else "yfinance"
        metrics = {
            "vwap": round(vwap, 4),
            "last": round(last_close, 4),
            "distance_from_vwap_pct": round(dist_pct, 3),
            "bars": len(df),
            "source": source,
        }
        if orb:
            metrics["or_high"] = round(orb["high"], 4)
            metrics["or_low"] = round(orb["low"], 4)

        max_dist = float(self.cfg["max_distance_from_vwap_pct"])
        if dist_pct > max_dist:
            return {"ok": False, "reason": f"price {dist_pct:.2f}% from VWAP (max {max_dist}%)",
                    "entry_price": proposed_entry, "metrics": metrics, "vwap": vwap, "opening_range": orb}

        if self.cfg.get("require_above_vwap") and last_close < vwap:
            return {"ok": False, "reason": "below VWAP",
                    "entry_price": proposed_entry, "metrics": metrics, "vwap": vwap, "opening_range": orb}

        adjusted = proposed_entry
        pullback_pct = float(self.cfg["vwap_pullback_pct"]) / 100.0
        if last_close > vwap:
            target = vwap * (1.0 + pullback_pct)
            adjusted = min(proposed_entry, round(max(vwap, target), 2))
        else:
            adjusted = min(proposed_entry, round(vwap * (1.0 + pullback_pct), 2))

        if self.cfg.get("allow_opening_range_breakout") and orb:
            if last_close > orb["high"]:
                metrics["setup"] = "or_breakout"
            elif orb["low"] <= last_close <= orb["high"]:
                metrics["setup"] = "or_pullback"
            else:
                metrics["setup"] = "below_or"

        return {
            "ok": True,
            "reason": f"intraday OK ({metrics.get('setup', 'vwap')}, dist {dist_pct:.2f}%)",
            "entry_price": adjusted,
            "vwap": vwap,
            "opening_range": orb,
            "metrics": metrics,
        }

    @staticmethod
    def _pass(entry, reason):
        return {"ok": True, "reason": reason, "entry_price": entry, "metrics": {}}
