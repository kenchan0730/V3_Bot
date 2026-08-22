"""Pyramiding rules: add only when winning; never average down."""

import logging

logger = logging.getLogger(__name__)


class PyramidManager:
    DEFAULTS = {
        "enabled": True,
        "allow_pyramid": True,
        "max_adds": 1,
        "min_profit_pct_to_add": 2.0,
        "add_size_fraction": 0.5,
        "forbid_averaging_down": True,
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}
        self._add_counts = {}

    def load_counts(self, data):
        self._add_counts = dict(data or {})

    def export_counts(self):
        return dict(self._add_counts)

    def can_add(self, symbol, current_price, avg_cost, quantity):
        if not self.cfg.get("enabled", True):
            return True, "pyramid off"

        if quantity <= 0:
            return True, "new entry"

        if self.cfg.get("forbid_averaging_down", True) and current_price < avg_cost:
            return False, f"禁止攤平：現價 ${current_price:.2f} < 成本 ${avg_cost:.2f}"

        profit_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost else 0
        min_profit = float(self.cfg.get("min_profit_pct_to_add", 2.0))
        if profit_pct < min_profit:
            return False, f"加倉需浮盈 ≥{min_profit:.1f}%（目前 {profit_pct:.1f}%）"

        adds = int(self._add_counts.get(symbol, 0))
        if adds >= int(self.cfg.get("max_adds", 1)):
            return False, f"已加倉 {adds} 次，達上限"

        if not self.cfg.get("allow_pyramid", True):
            return False, "pyramiding disabled"

        return True, f"允許加倉（浮盈 {profit_pct:.1f}%）"

    def record_add(self, symbol):
        self._add_counts[symbol] = int(self._add_counts.get(symbol, 0)) + 1

    def add_shares(self, base_shares):
        frac = float(self.cfg.get("add_size_fraction", 0.5))
        return max(1, int(base_shares * frac))
