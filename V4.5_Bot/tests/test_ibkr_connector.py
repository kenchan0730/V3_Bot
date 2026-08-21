"""IBKR connector tests using the FakeIB stand-in (no live connection)."""

import pytest

from core.ibkr_connector import IBKRConnector
from tests.helpers import (
    FakeAccountRow,
    FakeContract,
    FakeFill,
    FakeIB,
    FakeOrder,
    FakePosition,
    FakeTrade,
)


@pytest.fixture
def connector(fake_ib):
    return IBKRConnector(port=7497, account_mode="paper", ib=fake_ib)


# ----- lifecycle -----

def test_connect_success(connector, fake_ib):
    assert connector.connect() is True
    assert connector.connected is True
    assert fake_ib.isConnected() is True


def test_connect_rejects_live_port_in_paper_mode():
    conn = IBKRConnector(port=7496, account_mode="paper", ib=FakeIB())
    assert conn.connect() is False


def test_connect_retries_then_fails():
    conn = IBKRConnector(port=7497, max_retries=2, ib=FakeIB(fail_connect=True))
    assert conn.connect() is False
    assert conn.connected is False


def test_disconnect(connector):
    connector.connect()
    connector.disconnect()
    assert connector.connected is False


def test_is_connected_false_before_connect(connector):
    assert connector.is_connected() is False


def test_no_ib_instance_is_safe():
    conn = IBKRConnector(ib=None)
    conn.ib = None
    assert conn.connect() is False
    assert conn.is_connected() is False
    assert conn.sync_positions() == {}
    assert conn.get_account_values() == {}


# ----- positions & account (H1) -----

def test_sync_positions(connector):
    positions = connector.sync_positions()
    assert positions["AVAH"]["quantity"] == 10.0
    assert positions["AVAH"]["avg_cost"] == 12.0


def test_get_account_values(connector):
    values = connector.get_account_values()
    assert values["net_liquidation"] == 1000.0
    assert values["buying_power"] == 2000.0


def test_get_buying_power(connector):
    assert connector.get_buying_power() == 2000.0


def test_get_account_values_ignores_bad_numbers():
    ib = FakeIB(account=[FakeAccountRow("NetLiquidation", "not-a-number")])
    conn = IBKRConnector(ib=ib)
    assert conn.get_account_values().get("net_liquidation", 0.0) == 0.0


def test_realized_pnl_from_fills():
    ib = FakeIB(fills=[
        FakeFill("AVAH", "e1", realized_pnl=25.0),
        FakeFill("QXO", "e2", realized_pnl=-10.0),
    ])
    conn = IBKRConnector(ib=ib)
    total, new_ids, details = conn.get_realized_pnl_since()
    assert total == pytest.approx(15.0)
    assert set(new_ids) == {"e1", "e2"}
    assert len(details) == 2


def test_realized_pnl_skips_seen_executions():
    ib = FakeIB(fills=[FakeFill("AVAH", "e1", realized_pnl=25.0)])
    conn = IBKRConnector(ib=ib)
    total, new_ids, _ = conn.get_realized_pnl_since({"e1"})
    assert total == 0.0 and new_ids == []


# ----- bracket orders (H2) -----

def test_place_bracket_order_submits_three_legs(connector, fake_ib):
    connector.connect()
    result = connector.place_bracket_order("AVAH", 10, 12.0, 11.0, 14.0)
    assert result is not None
    assert result["stop"] == 11.0
    assert result["target"] == 14.0
    assert len(fake_ib.placed_orders) == 3


def test_place_bracket_order_requires_stop(connector):
    connector.connect()
    assert connector.place_bracket_order("AVAH", 10, 12.0, 0, 14.0) is None


def test_place_bracket_order_requires_positive_quantity(connector):
    connector.connect()
    assert connector.place_bracket_order("AVAH", 0, 12.0, 11.0, 14.0) is None


def test_place_bracket_order_requires_connection(connector):
    assert connector.place_bracket_order("AVAH", 10, 12.0, 11.0, 14.0) is None


def test_bracket_children_reference_parent(connector, fake_ib):
    connector.connect()
    connector.place_bracket_order("AVAH", 10, 12.0, 11.0, 14.0)
    parent, take_profit, stop_loss = (order for _, order in fake_ib.placed_orders)
    assert take_profit.parentId == parent.orderId
    assert stop_loss.parentId == parent.orderId
    assert stop_loss.transmit is True


# ----- single-leg orders -----

def test_place_order_with_retry(connector, fake_ib):
    connector.connect()
    trade = connector.place_order_with_retry("AVAH", "BUY", 5, limit_price=12.0)
    assert trade is not None
    assert len(fake_ib.placed_orders) == 1


def test_place_order_without_connection(connector):
    assert connector.place_order_with_retry("AVAH", "BUY", 5, limit_price=12.0) is None


# ----- cancellation (H3) -----

def test_cancel_orders_for_symbol(connector, fake_ib):
    connector.connect()
    fake_ib.open_trades = [
        FakeTrade(FakeContract("AVAH"), FakeOrder("BUY", 10, 12.0)),
        FakeTrade(FakeContract("QXO"), FakeOrder("BUY", 5, 20.0)),
    ]
    assert connector.cancel_orders_for_symbol("AVAH") == 1
    assert len(fake_ib.cancelled_orders) == 1


def test_cancel_orders_no_match(connector, fake_ib):
    connector.connect()
    fake_ib.open_trades = [FakeTrade(FakeContract("QXO"), FakeOrder())]
    assert connector.cancel_orders_for_symbol("AVAH") == 0


# ----- position exit (H3) -----

def test_close_position_flattens_long(connector, fake_ib):
    connector.connect()
    trade = connector.close_position("AVAH")
    assert trade is not None
    _, order = fake_ib.placed_orders[-1]
    assert order.action == "SELL"


def test_close_position_without_holding(connector, fake_ib):
    fake_ib._positions = []
    connector.connect()
    assert connector.close_position("AVAH") is None


def test_close_position_buys_back_short(fake_ib):
    fake_ib._positions = [FakePosition("AVAH", -8, 12.0)]
    conn = IBKRConnector(ib=fake_ib)
    conn.connect()
    conn.close_position("AVAH")
    _, order = fake_ib.placed_orders[-1]
    assert order.action == "BUY"


def test_get_open_orders(connector, fake_ib):
    connector.connect()
    fake_ib.open_trades = [FakeTrade(FakeContract("AVAH"), FakeOrder())]
    assert len(connector.get_open_orders()) == 1
