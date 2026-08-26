"""Read-only V4.5 analysis bridge for desktop app (no auto-trading)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BOT_ROOT = Path(__file__).resolve().parents[1]
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))


def _load_config() -> dict[str, Any]:
    from core.config_loader import load_config

    os.chdir(BOT_ROOT)
    return load_config(str(BOT_ROOT / "config.yaml"), str(BOT_ROOT / "data" / ".env"))


class DesktopAnalyzer:
    """Wraps V4.5 modules without IBKR order execution."""

    def __init__(self):
        self.config = _load_config()
        self._bot = None
        self._initialized = False

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

    def analyze_symbol(self, symbol: str) -> dict[str, Any]:
        self._ensure_bot()
        analysis = self._bot.analyze_symbol(symbol.upper())
        signal = analysis.signal or {}
        retail = None
        if analysis.ok and signal.get("action"):
            retail = self._bot.evaluate_retail(analysis)
        return {
            "symbol": symbol.upper(),
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

    def analyze_watchlist(self) -> list[dict[str, Any]]:
        self._ensure_bot()
        return self._bot.analyze_watchlist()

    def get_signals(self) -> list[dict[str, Any]]:
        """Buy/watch signals from watchlist analysis."""
        report = self.analyze_watchlist()
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
        return signals
