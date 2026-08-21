"""Shared pytest fixtures."""

import pandas as pd
import pytest

from tests.helpers import FakeAccountRow, FakeIB, FakePosition, make_ohlcv


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
