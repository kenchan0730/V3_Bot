"""Macro event calendar — reduce risk around CPI, FOMC, NFP (free schedule).

Uses a static schedule of known US release windows. For production, extend
with an API or manual overrides in config.
"""

import logging
from datetime import datetime, time as dt_time

import pytz

from core.market_calendar import MarketCalendar

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# Typical release times (ET). Dates are approximated monthly patterns.
RELEASE_WINDOWS = {
    "CPI": {"hour": 8, "minute": 30, "blackout_minutes_before": 120, "blackout_minutes_after": 60},
    "FOMC": {"hour": 14, "minute": 0, "blackout_minutes_before": 240, "blackout_minutes_after": 120},
    "NFP": {"hour": 8, "minute": 30, "blackout_minutes_before": 90, "blackout_minutes_after": 60},
}


class EconomicCalendar:
    DEFAULTS = {
        "enabled": True,
        "risk_multiplier": 0.5,
        "block_new_entries": False,
        "manual_events": [],
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}

    def _scheduled_today(self, now=None):
        now = now or datetime.now(ET)
        events = list(self.cfg.get("manual_events") or [])
        day = now.day
        weekday = now.weekday()

        # First Friday ≈ NFP
        if weekday == 4 and 1 <= day <= 7:
            events.append({"name": "NFP", **RELEASE_WINDOWS["NFP"]})
        # Mid-month CPI (~10th–15th, Tue–Thu)
        if 10 <= day <= 15 and weekday in (1, 2, 3):
            events.append({"name": "CPI", **RELEASE_WINDOWS["CPI"]})
        # FOMC: 3rd Wednesday-ish (simplified)
        if 15 <= day <= 22 and weekday == 2:
            events.append({"name": "FOMC", **RELEASE_WINDOWS["FOMC"]})

        return events

    def current_context(self, now=None):
        now = now or datetime.now(ET)
        if not self.cfg.get("enabled", True):
            return {"active": False, "risk_multiplier": 1.0, "events": [], "reason": "calendar off"}

        if not MarketCalendar.is_trading_day(now.date()):
            return {"active": False, "risk_multiplier": 1.0, "events": [], "reason": "non-trading day"}

        active_events = []
        min_multiplier = 1.0
        block = False

        for ev in self._scheduled_today(now):
            release = now.replace(
                hour=int(ev.get("hour", 8)),
                minute=int(ev.get("minute", 30)),
                second=0, microsecond=0,
            )
            before = int(ev.get("blackout_minutes_before", 60))
            after = int(ev.get("blackout_minutes_after", 30))
            start = release.timestamp() - before * 60
            end = release.timestamp() + after * 60
            if start <= now.timestamp() <= end:
                active_events.append(ev.get("name", "EVENT"))
                min_multiplier = min(min_multiplier, float(self.cfg.get("risk_multiplier", 0.5)))
                if self.cfg.get("block_new_entries"):
                    block = True

        if active_events:
            return {
                "active": True,
                "events": active_events,
                "risk_multiplier": min_multiplier,
                "block_new_entries": block,
                "reason": f"macro window: {','.join(active_events)} risk x{min_multiplier}",
            }
        return {"active": False, "risk_multiplier": 1.0, "events": [], "reason": "clear"}
