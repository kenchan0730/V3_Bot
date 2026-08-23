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
import yfinance as yf

from core.data_utils import normalize_columns

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
    }

    def __init__(self, config=None, ibkr=None):
        cfg = {**self.DEFAULTS, **(config or {})}
        self.cfg = cfg
        self.ibkr = ibkr

    def fetch_bars(self, symbol):
        """Return today's intraday OHLCV (lowercase columns, DatetimeIndex ET)."""
        df = None
        if self.ibkr and self.ibkr.is_connected():
            try:
                raw = self.ibkr.get_historical_data(
                    symbol, duration="1 D", bar_size=self.cfg["bar_size"]
                )
                if raw is not None and len(raw) >= self.cfg["min_intraday_bars"]:
                    df = normalize_columns(raw)
                    if "date" in df.columns:
                        df = df.set_index("date")
            except Exception as exc:
                logger.warning(f"{symbol} IBKR intraday failed: {exc}")

        if df is None or len(df) < self.cfg["min_intraday_bars"]:
            df = self._yf_intraday(symbol)

        if df is None or df.empty:
            return None

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        if df.index.tz is None:
            df.index = df.index.tz_localize(ET, ambiguous="NaT", nonexistent="NaT")
        else:
            df.index = df.index.tz_convert(ET)

        df = df.sort_index()
        today = datetime.now(ET).date()
        df = df[df.index.date == today]
        return df if len(df) >= max(3, self.cfg["min_intraday_bars"] // 4) else df

    def _yf_intraday(self, symbol):
        try:
            raw = yf.download(
                symbol, period="1d", interval=self.cfg["fallback_interval"],
                progress=False, prepost=False,
            )
            if raw is None or raw.empty:
                return None
            return normalize_columns(raw)
        except Exception as exc:
            logger.warning(f"{symbol} yfinance intraday failed: {exc}")
            return None

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

        vwap_series = self.compute_vwap(df)
        vwap = float(vwap_series.iloc[-1])
        last_close = float(df["close"].iloc[-1])
        dist_pct = abs(last_close - vwap) / vwap * 100.0 if vwap else 0.0

        orb = self.opening_range(df)
        metrics = {
            "vwap": round(vwap, 4),
            "last": round(last_close, 4),
            "distance_from_vwap_pct": round(dist_pct, 3),
            "bars": len(df),
            "source": "ibkr" if self.ibkr and self.ibkr.is_connected() else "yfinance",
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
