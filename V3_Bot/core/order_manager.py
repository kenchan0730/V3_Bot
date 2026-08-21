"""Order lifecycle tracking: submission, partial fills, timeout cancellation."""

import logging
import time

logger = logging.getLogger(__name__)

OPEN_STATUSES = {"PendingSubmit", "PreSubmitted", "Submitted", "ApiPending", "PendingCancel"}
DONE_STATUSES = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}


class ManagedOrder:
    def __init__(self, order_id, symbol, action, quantity, entry, stop, target, trade=None):
        self.order_id = order_id
        self.symbol = symbol
        self.action = action
        self.quantity = float(quantity)
        self.entry = entry
        self.stop = stop
        self.target = target
        self.trade = trade
        self.filled_qty = 0.0
        self.avg_fill_price = 0.0
        self.status = "SUBMITTED"
        self.submitted_at = time.time()
        self.last_update = self.submitted_at

    @property
    def remaining(self):
        return max(0.0, self.quantity - self.filled_qty)

    @property
    def is_open(self):
        return self.status not in DONE_STATUSES and self.remaining > 0

    def age_seconds(self):
        return time.time() - self.submitted_at

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "action": self.action,
            "quantity": self.quantity,
            "filled_qty": self.filled_qty,
            "remaining": self.remaining,
            "avg_fill_price": self.avg_fill_price,
            "status": self.status,
            "age_seconds": round(self.age_seconds(), 1),
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
        }


class OrderManager:
    """Tracks orders from submission to terminal state.

    Partial fills are surfaced via ``remaining``; stale working orders are
    cancelled after ``timeout_seconds``.
    """

    def __init__(self, ibkr=None, timeout_seconds=300, blotter=None, notifier=None):
        self.ibkr = ibkr
        self.timeout_seconds = int(timeout_seconds)
        self.blotter = blotter
        self.notifier = notifier
        self.orders = {}

    def track(self, order_id, symbol, action, quantity, entry=None, stop=None, target=None, trade=None):
        managed = ManagedOrder(order_id, symbol, action, quantity, entry, stop, target, trade)
        self.orders[order_id] = managed
        return managed

    def track_bracket(self, bracket):
        if not bracket:
            return None
        return self.track(
            bracket.get("parent_id"),
            bracket.get("symbol"),
            bracket.get("action", "BUY"),
            bracket.get("quantity", 0),
            entry=bracket.get("entry"),
            stop=bracket.get("stop"),
            target=bracket.get("target"),
            trade=(bracket.get("trades") or [None])[0],
        )

    def open_orders(self):
        return [o for o in self.orders.values() if o.is_open]

    def poll(self):
        """Refresh status/fills for tracked orders. Returns newly filled quantities."""
        updates = []
        for managed in list(self.orders.values()):
            trade = managed.trade
            if trade is None:
                continue
            status_obj = getattr(trade, "orderStatus", None)
            if status_obj is None:
                continue

            status = getattr(status_obj, "status", managed.status)
            filled = float(getattr(status_obj, "filled", 0) or 0)
            avg_price = float(getattr(status_obj, "avgFillPrice", 0) or 0)

            newly_filled = filled - managed.filled_qty
            if newly_filled > 0:
                managed.filled_qty = filled
                managed.avg_fill_price = avg_price or managed.avg_fill_price
                updates.append({
                    "order_id": managed.order_id,
                    "symbol": managed.symbol,
                    "action": managed.action,
                    "newly_filled": newly_filled,
                    "filled_qty": filled,
                    "avg_fill_price": managed.avg_fill_price,
                    "remaining": managed.remaining,
                    "partial": managed.remaining > 0,
                })
                if self.blotter:
                    self.blotter.log_fill(
                        managed.symbol, managed.action, newly_filled,
                        managed.avg_fill_price, managed.order_id,
                        status="PARTIAL" if managed.remaining > 0 else "FILLED",
                    )

            if status != managed.status:
                managed.status = status
                managed.last_update = time.time()
                if status in ("Cancelled", "ApiCancelled", "Inactive") and self.notifier:
                    self.notifier.alert_order_issue(
                        managed.symbol, f"訂單 {managed.order_id} 狀態 {status}"
                    )
        return updates

    def cancel_stale(self):
        """Cancel working orders older than the configured timeout."""
        cancelled = []
        for managed in self.open_orders():
            if managed.age_seconds() < self.timeout_seconds:
                continue
            logger.warning(
                f"⏱️ 訂單逾時取消: {managed.symbol} {managed.order_id} "
                f"({managed.age_seconds():.0f}s, 已成交 {managed.filled_qty}/{managed.quantity})"
            )
            if self.ibkr and managed.trade is not None:
                self.ibkr.cancel_order(getattr(managed.trade, "order", managed.trade))
            managed.status = "Cancelled"
            cancelled.append(managed.order_id)
            if self.blotter:
                self.blotter.log_event(
                    "ORDER_TIMEOUT", symbol=managed.symbol,
                    reason=f"逾時 {self.timeout_seconds}s 取消",
                    order_id=managed.order_id, filled_qty=managed.filled_qty,
                )
            if self.notifier:
                self.notifier.alert_order_issue(managed.symbol, f"訂單逾時已取消 ({managed.order_id})")
        return cancelled

    def snapshot(self):
        return [o.to_dict() for o in self.orders.values()]
