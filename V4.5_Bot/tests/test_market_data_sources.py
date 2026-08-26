from unittest.mock import MagicMock

import pandas as pd

from core.market_data_sources import fetch_daily_bars, fetch_intraday_bars


def _make_daily_df(n=70):
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 1_000_000,
        },
        index=idx,
    )


def test_fetch_daily_prefers_ibkr():
    ibkr = MagicMock()
    ibkr.is_connected.return_value = True
    ibkr.get_historical_data.return_value = _make_daily_df()
    df, source = fetch_daily_bars("AAPL", ibkr=ibkr, config={"daily_sources": ["ibkr", "yfinance"], "min_bars": 60})
    assert source == "ibkr"
    assert len(df) >= 60


def test_fetch_daily_falls_back_when_ibkr_empty():
    ibkr = MagicMock()
    ibkr.is_connected.return_value = True
    ibkr.get_historical_data.return_value = None
    df, source = fetch_daily_bars(
        "AAPL",
        ibkr=ibkr,
        config={"daily_sources": ["ibkr"], "min_bars": 60},
    )
    assert df is None
    assert source is None


def test_fetch_intraday_returns_none_without_sources():
    df, source = fetch_intraday_bars(
        "AAPL",
        ibkr=None,
        config={"intraday_sources": [], "min_intraday_bars": 12},
    )
    assert df is None
    assert source is None
