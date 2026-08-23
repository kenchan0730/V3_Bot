"""Single source of truth for capital, counters, and the realised P&L ledger.

Consolidates state that was previously duplicated between RiskManager and
EmotionManager (consecutive losses, daily trade count).
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2


class TradingState:
    def __init__(self, initial_capital=385.0, state_file="data/state.json"):
        self.initial_capital = float(initial_capital)
        self.total_capital = float(initial_capital)
        self.peak_capital = float(initial_capital)
        self.state_file = Path(state_file)

        self.consecutive_losses = 0
        self.today_trades = 0
        self.daily_realized_pnl = 0.0
        self.total_realized_pnl = 0.0
        self.trading_day = date.today().isoformat()
        self.ledger = []
        self.halted = False
        self.halt_reason = ""
        # Broker/portfolio snapshot published for the dashboard.
        self.positions = {}
        self.portfolio_snapshot = {}
        self.open_orders = []

    # ----- daily rollover -----

    def reset_daily_if_needed(self, today=None):
        today = (today or date.today()).isoformat() if not isinstance(today, str) else today
        if today != self.trading_day:
            logger.info(f"新交易日 {today}，重置每日計數器")
            self.trading_day = today
            self.today_trades = 0
            self.daily_realized_pnl = 0.0
            self.halted = False
            self.halt_reason = ""
            return True
        return False

    # ----- fills / P&L -----

    def record_fill(self, symbol, action, quantity, price, realized_pnl=0.0, order_id=None):
        """Record an execution and roll realised P&L into daily/total ledgers."""
        realized_pnl = float(realized_pnl)
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "realized_pnl": realized_pnl,
            "order_id": order_id,
        }
        self.ledger.append(entry)
        self.today_trades += 1

        if realized_pnl:
            self.apply_realized_pnl(realized_pnl)
        return entry

    def apply_realized_pnl(self, realized_pnl):
        realized_pnl = float(realized_pnl)
        self.daily_realized_pnl += realized_pnl
        self.total_realized_pnl += realized_pnl
        self.total_capital += realized_pnl
        if realized_pnl < 0:
            self.consecutive_losses += 1
        elif realized_pnl > 0:
            self.consecutive_losses = 0
        if self.total_capital > self.peak_capital:
            self.peak_capital = self.total_capital

    def sync_capital(self, net_liquidation):
        """Align capital with the broker's net liquidation value."""
        if net_liquidation and net_liquidation > 0:
            self.total_capital = float(net_liquidation)
            if self.total_capital > self.peak_capital:
                self.peak_capital = self.total_capital

    def halt(self, reason):
        self.halted = True
        self.halt_reason = reason

    def publish_portfolio(self, portfolio, total_capital, open_orders=None):
        """Expose the current book to the dashboard via the state file."""
        snapshot = portfolio.snapshot(total_capital)
        self.portfolio_snapshot = snapshot
        self.positions = snapshot.get("positions", {})
        self.open_orders = open_orders or []

    # ----- persistence -----

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "initial_capital": self.initial_capital,
            "total_capital": self.total_capital,
            "peak_capital": self.peak_capital,
            "consecutive_losses": self.consecutive_losses,
            "today_trades": self.today_trades,
            "daily_realized_pnl": self.daily_realized_pnl,
            "total_realized_pnl": self.total_realized_pnl,
            "trading_day": self.trading_day,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "positions": self.positions,
            "portfolio_snapshot": self.portfolio_snapshot,
            "open_orders": self.open_orders,
            "ledger": self.ledger[-500:],
        }

    def save(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            tmp.replace(self.state_file)
            logger.info(f"狀態已保存至 {self.state_file}")
            return True
        except Exception as e:
            logger.error(f"狀態保存失敗: {e}")
            return False

    def load(self):
        if not self.state_file.exists():
            return False
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"狀態載入失敗（將使用初始值）: {e}")
            return False

        version = data.get("schema_version", 1)
        if version > SCHEMA_VERSION:
            logger.warning(f"狀態檔版本 {version} 高於程式支援 {SCHEMA_VERSION}，忽略")
            return False

        self.initial_capital = float(data.get("initial_capital", self.initial_capital))
        self.total_capital = float(data.get("total_capital", self.total_capital))
        self.peak_capital = float(data.get("peak_capital", self.total_capital))
        self.consecutive_losses = int(data.get("consecutive_losses", 0))
        self.today_trades = int(data.get("today_trades", 0))
        self.daily_realized_pnl = float(data.get("daily_realized_pnl", 0.0))
        self.total_realized_pnl = float(data.get("total_realized_pnl", 0.0))
        self.trading_day = data.get("trading_day", self.trading_day)
        self.halted = bool(data.get("halted", False))
        self.halt_reason = data.get("halt_reason", "")
        self.positions = data.get("positions", {}) or {}
        self.portfolio_snapshot = data.get("portfolio_snapshot", {}) or {}
        self.open_orders = data.get("open_orders", []) or []
        self.ledger = data.get("ledger", [])
        logger.info(f"已載入狀態 ({data.get('saved_at', 'unknown')})")
        self.reset_daily_if_needed()
        return True
