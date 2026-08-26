"""Realtime cross-check: live quote vs last daily close + intraday momentum."""

from __future__ import annotations

import logging
from typing import Any

from core.market_data_sources import assess_quote_freshness, fetch_realtime_quote

logger = logging.getLogger(__name__)


class RealtimePulse:
    """Lightweight freshness and momentum probe before signal generation."""

    def __init__(self, config=None, ibkr=None):
        self.config = config or {}
        self.ibkr = ibkr
        self.enabled = bool(self.config.get("enabled", True))
        self.max_quote_age = int(self.config.get("max_quote_age_seconds", 900))
        self.warn_drift_pct = float(self.config.get("warn_drift_pct", 2.0))
        self.block_stale_quote = bool(self.config.get("block_stale_quote", False))

    def check(self, symbol: str, last_close: float | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": True, "skipped": True}

        quote = fetch_realtime_quote(symbol, ibkr=self.ibkr, config=self.config)
        freshness = assess_quote_freshness(quote, self.max_quote_age)
        price = quote.get("price")
        drift_pct = None
        if price and last_close and last_close > 0:
            drift_pct = abs(price - last_close) / last_close * 100.0

        result = {
            "ok": True,
            "quote": quote,
            "freshness": freshness,
            "drift_pct": round(drift_pct, 3) if drift_pct is not None else None,
            "source": quote.get("source"),
        }

        if freshness.get("stale"):
            msg = f"即時報價偏舊 ({freshness.get('reason')}, source={freshness.get('source')})"
            logger.info("   ⚡ %s %s", symbol, msg)
            result["warning"] = msg
            if self.block_stale_quote:
                result["ok"] = False
                result["reason"] = msg

        if drift_pct is not None and drift_pct >= self.warn_drift_pct:
            msg = f"盤中價格偏離昨收 {drift_pct:.2f}% (quote={price:.2f}, close={last_close:.2f})"
            logger.info("   ⚡ %s %s", symbol, msg)
            result["drift_warning"] = msg

        return result
