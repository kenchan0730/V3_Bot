"""Order lifecycle tracking: submission, partial fills, timeout cancellation."""

import logging
import time

logger = logging.getLogger(__name__)

OPEN_STATUSES = {"PendingSubmit", "PreSubmitted", "Submitted", "ApiPending", "PendingCancel"}
DONE_STATUSES = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}
# Statuses that mean a protective leg is genuinely working at the broker.
LIVE_STATUSES = OPEN_STATUSES | {"SUBMITTED"}


class ManagedOrder:
    def __init__(
        self, order_id, symbol, action, quantity, entry=None, stop=None, target=None,
        trade=None, role="entry", parent_id=None,
    ):
        self.order_id = order_id
        self.symbol = symbol
        self.action = action
        self.quantity = float(quantity)
        self.entry = entry
        self.stop = stop
        self.target = target
        self.trade = trade
        self.role = role
        self.parent_id = parent_id
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
        if self.role in ("stop_loss", "take_profit"):
            return self.status not in DONE_STATUSES
        return self.status not in DONE_STATUSES and self.remaining > 0

    def age_seconds(self):
        return time.time() - self.submitted_at

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "action": self.action,
            "role": self.role,
            "parent_id": self.parent_id,
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

    Bracket orders register entry + take-profit + stop-loss legs. Protective
    child legs are never cancelled by ``cancel_stale``.
    """

    def __init__(self, ibkr=None, timeout_seconds=300, blotter=None, notifier=None):
        self.ibkr = ibkr
        self.timeout_seconds = int(timeout_seconds)
        self.blotter = blotter
        self.notifier = notifier
        self.orders = {}

    def track(
        self, order_id, symbol, action, quantity, entry=None, stop=None, target=None,
        trade=None, role="entry", parent_id=None,
    ):
        """Register an order. Re-registering the same ``order_id`` is a no-op (idempotent)."""
        existing = self.orders.get(order_id)
        if existing is not None:
            return existing
        managed = ManagedOrder(
            order_id, symbol, action, quantity, entry, stop, target, trade,
            role=role, parent_id=parent_id,
        )
        self.orders[order_id] = managed
        return managed

    def _leg_role(self, index):
        if index == 0:
            return "entry"
        if index == 1:
            return "take_profit"
        return "stop_loss"

    def track_bracket(self, bracket):
        if not bracket:
            return None

        parent_id = bracket.get("parent_id")
        symbol = bracket.get("symbol")
        trades = bracket.get("trades") or []
        quantity = bracket.get("quantity", 0)
        action = bracket.get("action", "BUY")

        parent = None
        for index, trade in enumerate(trades):
            order = getattr(trade, "order", None)
            order_id = getattr(order, "orderId", None)
            if order_id is None:
                order_id = parent_id if index == 0 else f"{parent_id}-{index}"
            leg_action = getattr(order, "action", action if index == 0 else ("SELL" if action == "BUY" else "BUY"))
            role = self._leg_role(index)
            managed = self.track(
                order_id,
                symbol,
                leg_action,
                quantity,
                entry=bracket.get("entry"),
                stop=bracket.get("stop"),
                target=bracket.get("target"),
                trade=trade,
                role=role,
                parent_id=parent_id,
            )
            if index == 0:
                parent = managed

        if parent is None:
            parent = self.track(
                parent_id,
                symbol,
                action,
                quantity,
                entry=bracket.get("entry"),
                stop=bracket.get("stop"),
                target=bracket.get("target"),
                trade=trades[0] if trades else None,
                role="entry",
                parent_id=parent_id,
            )
        return parent

    def hydrate_from_broker(self):
        """Rebuild in-memory order tracking from broker open orders after restart."""
        if self.ibkr is None:
            return 0
        trades = self.ibkr.get_open_orders()
        added = 0
        for trade in trades or []:
            order = getattr(trade, "order", None)
            contract = getattr(trade, "contract", None)
            if order is None or contract is None:
                continue
            order_id = getattr(order, "orderId", None)
            if order_id is None or order_id in self.orders:
                continue

            symbol = getattr(contract, "symbol", "")
            action = getattr(order, "action", "")
            quantity = float(getattr(order, "totalQuantity", 0) or 0)
            parent_id = getattr(order, "parentId", None) or None
            order_type = str(getattr(order, "orderType", "") or "").upper()

            if parent_id:
                role = "stop_loss" if order_type in ("STP", "STP LMT", "TRAIL") else "take_profit"
            else:
                role = "entry"

            stop = None
            target = None
            entry = None
            if role == "stop_loss":
                stop = float(getattr(order, "auxPrice", 0) or 0) or None
            elif role == "take_profit":
                target = float(getattr(order, "lmtPrice", 0) or 0) or None
            else:
                entry = float(getattr(order, "lmtPrice", 0) or 0) or None

            status_obj = getattr(trade, "orderStatus", None)
            status = getattr(status_obj, "status", "SUBMITTED")
            filled = float(getattr(status_obj, "filled", 0) or 0)

            managed = self.track(
                order_id, symbol, action, quantity,
                entry=entry, stop=stop, target=target, trade=trade,
                role=role, parent_id=parent_id,
            )
            managed.status = status
            managed.filled_qty = filled
            added += 1
        if added:
            logger.info(f"已從 broker 恢復 {added} 筆掛單追蹤")
        return added

    def _sync_bracket_children(self, entry_managed):
        """Align protective leg quantities with the entry leg's filled size."""
        filled_qty = int(entry_managed.filled_qty)
        if filled_qty <= 0:
            return []

        updates = []
        for managed in self.orders.values():
            if managed.parent_id != entry_managed.order_id:
                continue
            if managed.role not in ("stop_loss", "take_profit"):
                continue
            if int(managed.quantity) == filled_qty:
                continue

            old_qty = managed.quantity
            managed.quantity = float(filled_qty)
            if self.ibkr and managed.trade is not None:
                self.ibkr.modify_order_quantity(managed.trade, filled_qty)
            updates.append({
                "order_id": managed.order_id,
                "symbol": managed.symbol,
                "role": managed.role,
                "old_qty": old_qty,
                "new_qty": filled_qty,
            })
            logger.info(
                f"📊 {managed.symbol} {managed.role} 數量同步 "
                f"{old_qty:.0f} → {filled_qty}（部分成交）"
            )
        return updates

    def open_orders(self):
        return [o for o in self.orders.values() if o.is_open]

    def legs_for_symbol(self, symbol):
        return [o for o in self.orders.values() if o.symbol == symbol]

    # ----- protection monitoring -----

    def stop_legs(self, symbol):
        return [
            o for o in self.orders.values()
            if o.symbol == symbol and o.role == "stop_loss"
        ]

    def has_live_stop(self, symbol):
        """True when a stop-loss leg is still working at the broker."""
        return any(o.status in LIVE_STATUSES for o in self.stop_legs(symbol))

    def protection_status(self, symbol):
        """Classify stop coverage: protected | triggered | unprotected | untracked."""
        legs = self.stop_legs(symbol)
        if not legs:
            return "untracked"
        if any(leg.status in LIVE_STATUSES for leg in legs):
            return "protected"
        if any(leg.status == "Filled" for leg in legs):
            return "triggered"
        return "unprotected"

    def check_protection(self, positions, stops=None, auto_rearm=True):
        """Find open positions with no working stop and optionally re-arm one.

        ``positions`` maps symbol -> {"quantity": n}; ``stops`` maps symbol ->
        stop price. Returns one report per at-risk symbol.
        """
        stops = stops or {}
        reports = []

        for symbol, pos in (positions or {}).items():
            try:
                quantity = float(pos.get("quantity", 0) if isinstance(pos, dict) else pos)
            except (TypeError, ValueError):
                continue
            if quantity <= 0:
                continue

            status = self.protection_status(symbol)
            if status in ("protected", "triggered"):
                continue

            stop_price = stops.get(symbol)
            report = {
                "symbol": symbol,
                "quantity": quantity,
                "status": status,
                "stop_price": stop_price,
                "rearmed": False,
            }

            logger.error(
                f"🚨 {symbol} 持倉 {quantity:.0f} 股偵測到停損保護缺失 ({status})"
            )
            if self.notifier:
                self.notifier.alert_order_issue(
                    symbol,
                    f"⚠️ 裸倉風險：停損單狀態 {status}，持倉 {quantity:.0f} 股無保護",
                )
            if self.blotter:
                self.blotter.log_event(
                    "STOP_MISSING", symbol=symbol,
                    reason=f"停損保護缺失 ({status})",
                    shares=quantity, stop_price=stop_price or "",
                )

            if auto_rearm and self.ibkr is not None and stop_price:
                trade = self.ibkr.place_protective_stop(symbol, int(quantity), stop_price)
                if trade is not None:
                    report["rearmed"] = True
                    order = getattr(trade, "order", None)
                    order_id = getattr(order, "orderId", f"{symbol}-rearm")
                    self.track(
                        order_id, symbol, "SELL", quantity,
                        stop=stop_price, trade=trade, role="stop_loss",
                    )
                    if self.notifier:
                        self.notifier.alert_order_issue(
                            symbol, f"🛡️ 已自動補掛保護性停損 @ ${stop_price}"
                        )
                    if self.blotter:
                        self.blotter.log_event(
                            "STOP_REARMED", symbol=symbol,
                            reason="自動補掛保護性停損",
                            shares=quantity, stop_price=stop_price,
                        )

            reports.append(report)

        return reports

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
                    "role": managed.role,
                    "newly_filled": newly_filled,
                    "filled_qty": filled,
                    "avg_fill_price": managed.avg_fill_price,
                    "remaining": managed.remaining,
                    "partial": managed.remaining > 0,
                })
                if managed.role == "entry":
                    child_updates = self._sync_bracket_children(managed)
                    if child_updates:
                        updates[-1]["child_qty_sync"] = child_updates
                if self.blotter:
                    self.blotter.log_fill(
                        managed.symbol, managed.action, newly_filled,
                        managed.avg_fill_price, managed.order_id,
                        status="PARTIAL" if managed.remaining > 0 else "FILLED",
                    )
                if managed.role in ("stop_loss", "take_profit") and self.notifier:
                    self.notifier.alert_order_issue(
                        managed.symbol,
                        f"{managed.role} 腿 {managed.order_id} 狀態更新 {status}",
                    )

            if status != managed.status:
                managed.status = status
                managed.last_update = time.time()
                if status in ("Cancelled", "ApiCancelled", "Inactive"):
                    msg = f"訂單 {managed.order_id} ({managed.role}) 狀態 {status}"
                    if managed.role == "stop_loss" and self.notifier:
                        self.notifier.alert_order_issue(
                            managed.symbol, f"⚠️ 停損單未被接收或已取消: {msg}"
                        )
                    elif self.notifier:
                        self.notifier.alert_order_issue(managed.symbol, msg)
        return updates

    def cancel_stale(self):
        """Cancel stale entry legs only; never drop protective stop/target children."""
        cancelled = []
        for managed in self.open_orders():
            if managed.role != "entry":
                continue
            if managed.age_seconds() < self.timeout_seconds:
                continue
            if managed.filled_qty > 0:
                logger.warning(
                    f"⏱️ 進場部分成交保留保護腿: {managed.symbol} "
                    f"({managed.filled_qty}/{managed.quantity})"
                )
                managed.status = "PartiallyFilled"
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
