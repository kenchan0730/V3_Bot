import time

import pytest

from core.order_manager import ManagedOrder, OrderManager
from tests.helpers import FakeContract, FakeIB, FakeOrder, FakeTrade


class RecordingBlotter:
    def __init__(self):
        self.fills = []
        self.events = []

    def log_fill(self, *args, **kwargs):
        self.fills.append((args, kwargs))

    def log_event(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))


class RecordingNotifier:
    def __init__(self):
        self.alerts = []

    def alert_order_issue(self, symbol, message):
        self.alerts.append((symbol, message))


@pytest.fixture
def manager():
    return OrderManager(ibkr=None, timeout_seconds=300,
                        blotter=RecordingBlotter(), notifier=RecordingNotifier())


def make_trade(symbol="AVAH", status="Submitted", filled=0, avg_price=0.0):
    return FakeTrade(FakeContract(symbol), FakeOrder("BUY", 10, 12.0), status, filled, avg_price)


def test_track_registers_order(manager):
    order = manager.track(1, "AVAH", "BUY", 10, entry=12.0, stop=11.0, target=14.0)
    assert order.remaining == 10
    assert order.is_open is True
    assert len(manager.open_orders()) == 1


def test_track_is_idempotent(manager):
    first = manager.track(42, "QXO", "BUY", 5, entry=10.0, stop=9.0, target=12.0)
    second = manager.track(42, "QXO", "BUY", 99, entry=99.0, stop=1.0, target=100.0)
    assert first is second
    assert second.quantity == 5
    assert len(manager.orders) == 1


def test_track_bracket(manager):
    bracket = {
        "parent_id": 7, "symbol": "AVAH", "action": "BUY", "quantity": 5,
        "entry": 12.0, "stop": 11.0, "target": 14.0, "trades": [make_trade()],
    }
    order = manager.track_bracket(bracket)
    assert order.order_id == 7
    assert order.stop == 11.0


def test_track_bracket_none(manager):
    assert manager.track_bracket(None) is None


def test_poll_records_full_fill(manager):
    trade = make_trade(filled=10, avg_price=12.05)
    manager.track(1, "AVAH", "BUY", 10, trade=trade)
    updates = manager.poll()
    assert len(updates) == 1
    assert updates[0]["filled_qty"] == 10
    assert updates[0]["partial"] is False
    assert manager.orders[1].remaining == 0


def test_poll_records_partial_fill(manager):
    trade = make_trade(filled=4, avg_price=12.0)
    manager.track(1, "AVAH", "BUY", 10, trade=trade)
    updates = manager.poll()
    assert updates[0]["partial"] is True
    assert updates[0]["remaining"] == 6
    assert manager.blotter.fills


def test_poll_incremental_fills(manager):
    trade = make_trade(filled=4)
    managed = manager.track(1, "AVAH", "BUY", 10, trade=trade)
    manager.poll()
    trade.orderStatus.filled = 10
    updates = manager.poll()
    assert updates[0]["newly_filled"] == 6
    assert managed.filled_qty == 10


def test_poll_no_change_returns_empty(manager):
    manager.track(1, "AVAH", "BUY", 10, trade=make_trade())
    manager.poll()
    assert manager.poll() == []


def test_poll_ignores_untracked_trade(manager):
    manager.track(1, "AVAH", "BUY", 10, trade=None)
    assert manager.poll() == []


def test_poll_alerts_on_cancellation(manager):
    trade = make_trade(status="Cancelled")
    manager.track(1, "AVAH", "BUY", 10, trade=trade)
    manager.poll()
    assert manager.notifier.alerts


def test_cancel_stale_cancels_old_orders():
    ib = FakeIB()
    manager = OrderManager(ibkr=None, timeout_seconds=0,
                           blotter=RecordingBlotter(), notifier=RecordingNotifier())
    manager.track(1, "AVAH", "BUY", 10, trade=make_trade())
    time.sleep(0.01)
    cancelled = manager.cancel_stale()
    assert cancelled == [1]
    assert manager.orders[1].status == "Cancelled"
    assert manager.blotter.events


def test_cancel_stale_keeps_fresh_orders(manager):
    manager.track(1, "AVAH", "BUY", 10, trade=make_trade())
    assert manager.cancel_stale() == []


def test_cancel_stale_calls_broker():
    from core.ibkr_connector import IBKRConnector

    fake_ib = FakeIB()
    connector = IBKRConnector(ib=fake_ib)
    connector.connect()
    manager = OrderManager(ibkr=connector, timeout_seconds=0)
    manager.track(1, "AVAH", "BUY", 10, trade=make_trade())
    manager.cancel_stale()
    assert len(fake_ib.cancelled_orders) == 1


def test_managed_order_serialization():
    order = ManagedOrder(1, "AVAH", "BUY", 10, 12.0, 11.0, 14.0)
    data = order.to_dict()
    assert data["symbol"] == "AVAH"
    assert data["remaining"] == 10
    assert "age_seconds" in data


def test_snapshot_lists_orders(manager):
    manager.track(1, "AVAH", "BUY", 10, trade=make_trade())
    manager.track(2, "QXO", "BUY", 5, trade=make_trade("QXO"))
    assert len(manager.snapshot()) == 2
