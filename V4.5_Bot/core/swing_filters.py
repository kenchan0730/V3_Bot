"""Swing-trading quality gates: sector rotation, RSI, confluence, bad-trade rejection.

Research-backed filters (2025–2026 swing literature):
- Trade longs in top relative-strength sectors vs SPY
- RSI 30–68 confluence with trend (avoid chasing overbought)
- Volume confirmation on breakouts (>1.2–1.5× average)
- Minimum confluence score before entry
"""

from __future__ import annotations

import logging
from typing import Any

from core.sector_tracker import SectorTracker

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": False,
    "mode": "swing",
    "strong_min_confluence": 6,
    "moderate_min_confluence": 5,
    "moderate_min_edges": 4,
    "moderate_size_factor": 0.5,
    "trend_mode": "swing",
    "rsi_min": 28,
    "rsi_max": 68,
    "reject_rsi_above": 72,
    "require_sector_alignment": True,
    "sector_filter_mode": "soft",
    "sector_block_rs_below": -4.0,
    "min_sector_rs_pct": -2.0,
    "top_sectors_count": 4,
    "min_market_breadth": 35,
    "block_learned_losers": True,
    "require_bullish_candle_for_moderate": True,
    "zscore_max": 1.45,
    "min_vol_ratio": 0.0,
    "require_price_above_ma20": False,
    "min_strong_edges_strong": 0,
    "min_strong_edges_moderate": 0,
}


class SwingQualityFilter:
    """Post-signal gate: reject low-quality setups while allowing moderate frequency."""

    def __init__(self, config=None, portfolio=None):
        self.cfg = {**DEFAULTS, **(config or {})}
        self.portfolio = portfolio
        self._sector_cache: dict[str, Any] | None = None

    def refresh_sector_context(self, force=False):
        if self._sector_cache is None or force:
            self._sector_cache = SectorTracker.get_market_sector_context(
                period=self.cfg.get("sector_lookback", "1mo"),
                top_n=int(self.cfg.get("top_sectors_count", 4)),
            )
        return self._sector_cache

    def sector_of(self, symbol: str) -> str:
        if self.portfolio:
            return self.portfolio.sector_of(symbol)
        return "Unknown"

    def _threshold(self, context, key, default):
        """Config value, unless the pacer supplied an effective override."""
        overrides = getattr(context, "threshold_overrides", None) or {}
        if key in overrides:
            return overrides[key]
        return self.cfg.get(key, default)

    def validate(self, symbol, signal, context, df=None):
        """Return (ok, reason)."""
        if not self.cfg.get("enabled", True):
            return True, "swing filters disabled"

        action = signal.get("action", "HOLD")
        if action not in ("STRONG_BUY", "MODERATE_BUY", "BUY"):
            return True, "not a buy"

        track = signal.get("track") or ("STRONG" if action == "STRONG_BUY" else "MODERATE")
        confluence = int(signal.get("confluence_score") or 0)
        min_conf = int(
            self._threshold(context, "strong_min_confluence", 6)
            if track == "STRONG"
            else self._threshold(context, "moderate_min_confluence", 5)
        )
        if confluence < min_conf:
            return False, f"共振 {confluence}/10 < 門檻 {min_conf} ({track})"

        strong_edges = signal.get("strong_edges") or []
        min_strong = int(
            self.cfg.get("min_strong_edges_strong", 0)
            if track == "STRONG"
            else self.cfg.get("min_strong_edges_moderate", 0)
        )
        if min_strong and len(strong_edges) < min_strong:
            return False, f"強化邊緣 {len(strong_edges)} < {min_strong} ({track})"

        min_vol = float(self.cfg.get("min_vol_ratio", 0))
        vol_ratio = float(context.vol_ratio or 0)
        if min_vol > 0 and vol_ratio < min_vol:
            return False, f"量比 {vol_ratio:.2f} < {min_vol:.2f}"

        if self.cfg.get("require_price_above_ma20") and context.ma20:
            if float(context.price) <= float(context.ma20):
                return False, f"價格 {context.price:.2f} <= MA20 {context.ma20:.2f}"

        quant = context.quant or {}
        rsi = float(quant.get("rsi") or 50)
        z_score = float(quant.get("z_score") or 0)

        reject_rsi = float(self._threshold(context, "reject_rsi_above", 72))
        if rsi > reject_rsi:
            return False, f"RSI {rsi:.1f} 超買 (> {reject_rsi})"

        rsi_max = float(self._threshold(context, "rsi_max", 68))
        if rsi > rsi_max and track == "MODERATE":
            return False, f"RSI {rsi:.1f} 偏高，MODERATE 不做追價"

        rsi_min = float(self.cfg.get("rsi_min", 28))
        if rsi < rsi_min and float(context.vol_ratio or 1) < 1.2:
            return False, f"RSI {rsi:.1f} 過低且量能不足（避免接刀）"

        zmax = float(self._threshold(context, "zscore_max", 1.45))
        if z_score > zmax:
            return False, f"Z-Score {z_score:.2f} 過熱 (> {zmax})"

        learned = signal.get("learned_candle") or {}
        if self.cfg.get("block_learned_losers") and learned.get("blocked"):
            return False, f"Candle Lab 阻擋: {learned.get('reason', '低勝率形態')}"

        breadth = context.breadth_score
        min_breadth = float(self.cfg.get("min_market_breadth", 35))
        if breadth is not None and breadth < min_breadth:
            return False, f"市場廣度 {breadth:.0f} < {min_breadth}"

        if self.cfg.get("require_sector_alignment", True):
            ok, msg = self._check_sector(symbol)
            if not ok:
                return False, msg

        return True, f"品質 OK ({track}, 共振 {confluence}, RSI {rsi:.1f})"

    def _check_sector(self, symbol: str):
        if not self.cfg.get("require_sector_alignment", True):
            return True, "sector filter off"

        mode = str(self.cfg.get("sector_filter_mode", "soft")).lower()
        ctx = self.refresh_sector_context()
        sector = self.sector_of(symbol)
        normalized = SectorTracker.normalize_sector_name(sector)
        leading = ctx.get("leading_sectors") or []
        rs_map = ctx.get("relative_strength") or {}
        rs = rs_map.get(normalized)
        min_rs = float(self.cfg.get("min_sector_rs_pct", -2.0))
        block_below = float(self.cfg.get("sector_block_rs_below", -4.0))

        if mode == "off":
            return True, "sector filter off"
        if mode == "soft":
            if rs is not None and rs < block_below:
                return False, f"板塊 {normalized} 極弱 RS {rs:+.2f}% (< {block_below}%)"
            hint = "領先" if normalized in leading else "追蹤"
            return True, f"板塊 {hint} {normalized} (RS {rs:+.2f}%)" if rs is not None else f"板塊 {normalized}"

        if normalized in leading:
            return True, f"板塊 {normalized} 領先"
        if rs is not None and rs >= min_rs:
            return True, f"板塊 {normalized} RS {rs:+.2f}%"
        top = ", ".join(leading[:4]) or "n/a"
        return False, f"板塊 {normalized} 弱於市場 (領先: {top})"

    def market_summary(self) -> str:
        ctx = self.refresh_sector_context()
        leading = ctx.get("leading_sectors") or []
        theme = ctx.get("theme_hint") or "mixed"
        return f"板塊領先: {', '.join(leading[:4])} | 市場偏向: {theme}"
