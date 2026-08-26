"""Read-only V4.5 analysis bridge for desktop app (no auto-trading)."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BOT_ROOT = Path(__file__).resolve().parents[1]
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

MAX_DESKTOP_WATCHLIST_ANALYSIS = 8
SIGNAL_CACHE_TTL = 300
SYMBOL_ANALYSIS_TTL = 120


def _load_config() -> dict[str, Any]:
    from core.config_loader import load_config

    os.chdir(BOT_ROOT)
    return load_config(str(BOT_ROOT / "config.yaml"), str(BOT_ROOT / "data" / ".env"))


def _retail_to_dict(retail) -> dict[str, Any] | None:
    if retail is None:
        return None
    return {
        "approve": retail.approve,
        "verdict": retail.verdict,
        "retail_score": retail.retail_score,
        "size_factor": retail.size_factor,
        "summary": retail.summary(),
        "reasons": list(retail.reasons or []),
        "metrics": dict(retail.metrics or {}),
    }


class DesktopAnalyzer:
    """Wraps V4.5 modules without IBKR order execution."""

    def __init__(self):
        self.config = _load_config()
        self._bot = None
        self._initialized = False
        self._signal_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._symbol_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _ensure_bot(self):
        if self._initialized:
            return
        os.chdir(BOT_ROOT)
        from main import TradingBot

        cfg = dict(self.config)
        trading = dict(cfg.get("trading") or {})
        trading["auto_trade"] = False
        cfg["trading"] = trading
        self._bot = TradingBot(cfg, dry_run=True)
        self._bot.auto_trade = False
        self._initialized = True

    def analyze_symbol(self, symbol: str, use_cache: bool = True) -> dict[str, Any]:
        sym = symbol.upper()
        if use_cache:
            cached = self._symbol_cache.get(sym)
            if cached and (time.time() - cached[0]) < SYMBOL_ANALYSIS_TTL:
                return cached[1]

        self._ensure_bot()
        analysis = self._bot.analyze_symbol(sym)
        signal = analysis.signal or {}
        retail = None
        if analysis.ok and signal.get("action"):
            retail = _retail_to_dict(self._bot.evaluate_retail(analysis))

        result = {
            "symbol": sym,
            "stage": analysis.stage,
            "ok": analysis.ok,
            "price": analysis.price,
            "reason": analysis.reason,
            "fundamental": analysis.fundamental_view,
            "news": analysis.news_view,
            "quant": analysis.quant,
            "signal": signal,
            "quality_ok": analysis.quality_ok,
            "quality_reason": analysis.quality_reason,
            "retail": retail,
        }
        self._symbol_cache[sym] = (time.time(), result)
        return result

    def analyze_watchlist(self) -> dict[str, Any]:
        self._ensure_bot()
        return self._bot.analyze_watchlist()

    def get_signals(self, force: bool = False) -> list[dict[str, Any]]:
        """Buy/watch signals — cached, limited to top watchlist names."""
        if not force and self._signal_cache:
            ts, data = self._signal_cache
            if (time.time() - ts) < SIGNAL_CACHE_TTL:
                return data

        self._ensure_bot()
        watchlist = list(self._bot.watchlist[:MAX_DESKTOP_WATCHLIST_ANALYSIS])
        original = self._bot.watchlist
        self._bot.watchlist = watchlist
        try:
            report = self._bot.analyze_watchlist()
        finally:
            self._bot.watchlist = original

        rows = report.get("symbols") or []
        signals = []
        for row in rows:
            action = row.get("action")
            verdict = row.get("verdict")
            if action in ("STRONG_BUY", "MODERATE_BUY") or verdict in ("BUY", "WATCH"):
                signals.append({
                    "symbol": row.get("symbol"),
                    "action": action,
                    "verdict": verdict,
                    "price": row.get("price"),
                    "tier": row.get("tier"),
                    "reason": row.get("reason"),
                    "confluence": row.get("confluence"),
                    "retail_score": row.get("retail_score"),
                })
        self._signal_cache = (time.time(), signals)
        return signals
