import pandas as pd
import pytest

from core.data_utils import normalize_columns


@pytest.fixture
def uppercase_ohlcv_df():
    return pd.DataFrame({
        "Open": [10.0, 11.0, 12.0, 13.0, 14.0],
        "High": [11.0, 12.0, 13.0, 14.0, 15.0],
        "Low": [9.0, 10.0, 11.0, 12.0, 13.0],
        "Close": [10.5, 11.5, 12.5, 13.5, 14.5],
        "Volume": [1000, 1100, 1200, 1300, 1400],
    })


def test_normalize_columns_lowercases_names(uppercase_ohlcv_df):
    result = normalize_columns(uppercase_ohlcv_df)
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]


def test_normalize_columns_is_idempotent(uppercase_ohlcv_df):
    once = normalize_columns(uppercase_ohlcv_df)
    twice = normalize_columns(once)
    assert list(twice.columns) == ["open", "high", "low", "close", "volume"]


def test_normalize_columns_returns_copy(uppercase_ohlcv_df):
    result = normalize_columns(uppercase_ohlcv_df)
    result["close"] = 0
    assert uppercase_ohlcv_df["Close"].iloc[-1] != 0


def test_normalize_columns_multindex():
    arrays = [["Close", "Close"], ["AAPL", "MSFT"]]
    df = pd.DataFrame([[1.0, 2.0]], columns=pd.MultiIndex.from_arrays(arrays))
    result = normalize_columns(df)
    assert "close" in result.columns
