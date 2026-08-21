"""Shared fixtures: synthetic OHLCV data and IBKR fakes."""

import pandas as pd
import pytest


def make_ohlcv(closes, volumes=None, start="2024-01-01"):
    """Build a lowercase OHLCV frame with a DatetimeIndex."""
    volumes = volumes or [1_000_000] * len(closes)
    index = pd.bdate_range(start=start, periods=len(closes))
    rows = []
    for i, close in enumerate(closes):
        rows.append({
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volumes[i],
        })
    return pd.DataFrame(rows, index=index)


@pytest.fixture
def trending_df():
    closes = [10 + i * 0.1 for i in range(120)]
    volumes = [1_000_000 + (i % 5) * 100_000 for i in range(120)]
    return make_ohlcv(closes, volumes)


@pytest.fixture
def fresh_df():
    """Frame whose final bar is today, so freshness checks pass."""
    closes = [10 + i * 0.05 for i in range(80)]
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=len(closes))
    df = make_ohlcv(closes)
    df.index = index
    return df


# ----- IBKR fakes -----

class FakeContract:
    def __init__(self, symbol):
        self.symbol = symbol


class FakePosition:
    def __init__(self, symbol, position, avg_cost):
        self.contract = FakeContract(symbol)
        self.position = position
        self.avgCost = avg_cost


class FakeAccountRow:
    def __init__(self, tag, value):
        self.tag = tag
        self.value = value


class FakeOrder:
    _next_id = 1

    def __init__(self, action="BUY", quantity=0, price=None):
        self.action = action
        self.totalQuantity = quantity
        self.lmtPrice = price
        self.orderId = FakeOrder._next_id
        FakeOrder._next_id += 1
        self.transmit = True
        self.parentId = None


class FakeOrderStatus:
    def __init__(self, status="Submitted", filled=0, avg_fill_price=0.0):
        self.status = status
        self.filled = filled
        self.avgFillPrice = avg_fill_price


class FakeTrade:
    def __init__(self, contract, order, status="Submitted", filled=0, avg_fill_price=0.0):
        self.contract = contract
        self.order = order
        self.orderStatus = FakeOrderStatus(status, filled, avg_fill_price)


class FakeExecution:
    def __init__(self, exec_id, side="BOT", shares=10, price=10.0):
        self.execId = exec_id
        self.side = side
        self.shares = shares
        self.price = price


class FakeCommissionReport:
    def __init__(self, realized_pnl=0.0, commission=1.0):
        self.realizedPNL = realized_pnl
        self.commission = commission


class FakeFill:
    def __init__(self, symbol, exec_id, realized_pnl=0.0, shares=10, price=10.0, side="BOT"):
        self.contract = FakeContract(symbol)
        self.execution = FakeExecution(exec_id, side, shares, price)
        self.commissionReport = FakeCommissionReport(realized_pnl)


class FakeIB:
    """Minimal ib_insync stand-in for connector tests."""

    def __init__(self, positions=None, account=None, fills=None, fail_connect=False):
        self._positions = positions or []
        self._account = account or []
        self._fills = fills or []
        self._connected = False
        self.fail_connect = fail_connect
        self.placed_orders = []
        self.cancelled_orders = []
        self.open_trades = []

    def connect(self, host, port, clientId=None):
        if self.fail_connect:
            raise ConnectionError("refused")
        self._connected = True

    def disconnect(self):
        self._connected = False

    def isConnected(self):
        return self._connected

    def positions(self):
        return self._positions

    def accountSummary(self):
        return self._account

    def fills(self):
        return self._fills

    def placeOrder(self, contract, order):
        self.placed_orders.append((contract, order))
        trade = FakeTrade(contract, order)
        self.open_trades.append(trade)
        return trade

    def cancelOrder(self, order):
        self.cancelled_orders.append(order)

    def openTrades(self):
        return list(self.open_trades)

    def reqHistoricalData(self, *args, **kwargs):
        return []


@pytest.fixture
def fake_ib():
    return FakeIB(
        positions=[FakePosition("AVAH", 10, 12.0)],
        account=[
            FakeAccountRow("NetLiquidation", "1000"),
            FakeAccountRow("BuyingPower", "2000"),
            FakeAccountRow("AvailableFunds", "800"),
        ],
    )
