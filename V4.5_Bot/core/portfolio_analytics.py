"""Portfolio heat, rebalance hints, strategic cash tracking."""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PortfolioAnalytics:
    """Answers: if market drops 2%, how much do we lose?"""

    heat_2pct_pullback_usd: float = 0.0
    heat_2pct_pullback_pct: float = 0.0
    max_symbol_weight_pct: float = 0.0
    max_symbol: str = ""
    rebalance_needed: bool = False
    rebalance_reason: str = ""
    notes: list = field(default_factory=list)


class PortfolioHeatMonitor:
    DEFAULTS = {
        "enabled": True,
        "market_pullback_pct": 2.0,
        "max_symbol_weight_pct": 35.0,
        "rebalance_threshold_pct": 40.0,
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}

    def analyze(self, portfolio, total_capital):
        result = PortfolioAnalytics()
        if not self.cfg.get("enabled", True) or total_capital <= 0:
            return result

        pullback = float(self.cfg.get("market_pullback_pct", 2.0)) / 100.0
        gross = portfolio.gross_exposure()
        result.heat_2pct_pullback_usd = round(gross * pullback, 2)
        result.heat_2pct_pullback_pct = round(gross / total_capital * pullback * 100, 2)

        max_sym, max_w = "", 0.0
        for symbol, pos in portfolio.positions.items():
            w = pos["market_value"] / total_capital * 100
            if w > max_w:
                max_w, max_sym = w, symbol
        result.max_symbol_weight_pct = round(max_w, 2)
        result.max_symbol = max_sym

        threshold = float(self.cfg.get("rebalance_threshold_pct", 40))
        if max_w > threshold:
            result.rebalance_needed = True
            result.rebalance_reason = f"{max_sym} 佔 {max_w:.1f}% > {threshold}%"
            result.notes.append("考慮減倉獲利標的、恢復分散")

        max_single = float(self.cfg.get("max_symbol_weight_pct", 35))
        if max_w > max_single:
            result.notes.append(f"單一標的集中度 {max_w:.1f}% 超過目標 {max_single}%")

        return result
