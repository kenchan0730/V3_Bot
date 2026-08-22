"""US Pattern Day Trader (PDT) guard for accounts under $25k."""

import logging
from datetime import date

logger = logging.getLogger(__name__)


class PDTGuard:
    DEFAULTS = {
        "enabled": True,
        "min_equity": 25000.0,
        "max_day_trades_rolling": 3,
        "rolling_days": 5,
    }

    def __init__(self, config=None, state=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}
        self.state = state
        self._day_trade_log = []

    def load_from_state(self, state_data):
        self._day_trade_log = list(state_data.get("pdt_day_trades", []))

    def export_to_state(self):
        return {"pdt_day_trades": self._day_trade_log[-20:]}

    def record_day_trade(self, symbol, trade_date=None):
        trade_date = (trade_date or date.today()).isoformat()
        self._day_trade_log.append({"date": trade_date, "symbol": symbol})

    def count_recent_day_trades(self, reference=None):
        reference = reference or date.today()
        window = int(self.cfg.get("rolling_days", 5))
        cutoff = reference.toordinal() - window
        count = 0
        for entry in self._day_trade_log:
            try:
                d = date.fromisoformat(entry["date"])
                if d.toordinal() >= cutoff:
                    count += 1
            except (ValueError, KeyError):
                continue
        return count

    def check(self, equity, is_day_trade=False):
        if not self.cfg.get("enabled", True):
            return True, "PDT guard off"

        min_eq = float(self.cfg.get("min_equity", 25000))
        if equity >= min_eq:
            return True, "equity above PDT threshold"

        if is_day_trade:
            recent = self.count_recent_day_trades()
            limit = int(self.cfg.get("max_day_trades_rolling", 3))
            if recent >= limit:
                return False, (
                    f"PDT: 權益 ${equity:.0f} < ${min_eq:.0f}，"
                    f"5日內已 {recent} 次 day trade（上限 {limit}）"
                )
        return True, "PDT OK (swing mode)"

    def classify_hold(self, entry_is_today, exit_is_today):
        return entry_is_today and exit_is_today
