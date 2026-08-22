"""Liquidity black-hole windows: opening/closing buffers, macro overlap."""

import logging
from datetime import datetime, time as dt_time

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


class LiquidityGuard:
    DEFAULTS = {
        "enabled": True,
        "avoid_first_minutes": 5,
        "avoid_last_minutes": 10,
        "avoid_market_orders_on_open": True,
        "widen_stop_near_open": True,
        "open_stop_buffer_pct": 0.3,
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}

    def session_phase(self, now=None):
        now = now or datetime.now(ET)
        if now.weekday() >= 5:
            return "closed", "weekend"

        open_t = dt_time(9, 30)
        close_t = dt_time(16, 0)
        t = now.time()
        if t < open_t or t > close_t:
            return "closed", "outside RTH"

        open_min = open_t.hour * 60 + open_t.minute + int(self.cfg.get("avoid_first_minutes", 5))
        close_min = close_t.hour * 60 + close_t.minute - int(self.cfg.get("avoid_last_minutes", 10))
        now_min = t.hour * 60 + t.minute

        if now_min < open_min:
            return "open_chaos", f"開盤前 {self.cfg.get('avoid_first_minutes')} 分鐘"
        if now_min > close_min:
            return "close_chaos", f"收盤前 {self.cfg.get('avoid_last_minutes')} 分鐘"
        return "normal", "OK"

    def allow_new_entry(self, now=None):
        if not self.cfg.get("enabled", True):
            return True, "liquidity guard off"
        phase, reason = self.session_phase(now)
        if phase in ("open_chaos", "close_chaos"):
            return False, f"流動性黑洞: {reason}"
        return True, reason

    def adjust_stop(self, stop, entry, side="long"):
        if not self.cfg.get("widen_stop_near_open"):
            return stop
        phase, _ = self.session_phase()
        if phase != "open_chaos" or not stop:
            return stop
        buffer = float(self.cfg.get("open_stop_buffer_pct", 0.3)) / 100.0
        if side == "long":
            return round(stop * (1 - buffer), 2)
        return round(stop * (1 + buffer), 2)
