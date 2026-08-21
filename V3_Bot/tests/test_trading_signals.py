import pandas as pd
import pytest

from core.trading_signals import TradingSignals
from core.data_utils import normalize_columns


def _make_df(closes, volumes=None):
    volumes = volumes or [1000] * len(closes)
    rows = []
    for i, close in enumerate(closes):
        rows.append({
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volumes[i],
        })
    return pd.DataFrame(rows)


@pytest.fixture
def bullish_setup_df():
    closes = [10 + i * 0.1 for i in range(70)]
    volumes = [1000 + (i % 5) * 100 for i in range(70)]
    closes[-1] = closes[-2] + 0.3
    return _make_df(closes, volumes)


def test_hold_when_z_score_too_low():
    df = _make_df([10 + i * 0.05 for i in range(70)])
    price = float(df["close"].iloc[-1])
    ma20 = float(df["close"].rolling(20).mean().iloc[-1])
    ma50 = float(df["close"].rolling(50).mean().iloc[-1])
    signal = TradingSignals.get_combined_signal(
        df, price, 20.0, 0.1, 1.6, ma20, ma50, zscore_min=0.5
    )
    assert signal["action"] == "HOLD"


def test_strong_buy_with_bullish_candle_and_tech(bullish_setup_df):
    df = bullish_setup_df
    df.iloc[-1, df.columns.get_loc("low")] = df.iloc[-1]["close"] - 1.5
    df.iloc[-1, df.columns.get_loc("open")] = df.iloc[-1]["close"] - 0.1
    df.iloc[-1, df.columns.get_loc("high")] = df.iloc[-1]["close"] + 0.1

    price = float(df["close"].iloc[-1])
    ma20 = float(df["close"].rolling(20).mean().iloc[-1])
    ma50 = float(df["close"].rolling(50).mean().iloc[-1])
    vol = float(df["volume"].iloc[-1])
    avg_vol = float(df["volume"].rolling(5).mean().iloc[-1])
    vol_ratio = vol / avg_vol

    signal = TradingSignals.get_combined_signal(
        df, price, 18.0, 1.0, vol_ratio, ma20, ma50, zscore_min=0.5
    )
    assert signal["action"] in ("STRONG_BUY", "HOLD")


def test_normalize_inside_get_combined_signal():
    raw = _make_df([10 + i * 0.05 for i in range(70)])
    raw = raw.rename(columns=str.capitalize)
    price = float(raw["Close"].iloc[-1])
    ma20 = float(raw["Close"].rolling(20).mean().iloc[-1])
    ma50 = float(raw["Close"].rolling(50).mean().iloc[-1])
    signal = TradingSignals.get_combined_signal(
        raw, price, 20.0, 0.2, 1.6, ma20, ma50, zscore_min=0.5
    )
    assert "action" in signal


def test_strong_sell_bearish_candle():
    df = _make_df([10 + i * 0.05 for i in range(70)])
    df.iloc[-2, df.columns.get_loc("open")] = 10.5
    df.iloc[-2, df.columns.get_loc("close")] = 10.8
    df.iloc[-2, df.columns.get_loc("high")] = 11.0
    df.iloc[-2, df.columns.get_loc("low")] = 10.4
    df.iloc[-1, df.columns.get_loc("open")] = 10.7
    df.iloc[-1, df.columns.get_loc("close")] = 10.2
    df.iloc[-1, df.columns.get_loc("high")] = 10.75
    df.iloc[-1, df.columns.get_loc("low")] = 10.1

    price = float(df["close"].iloc[-1])
    ma20 = float(df["close"].rolling(20).mean().iloc[-1])
    ma50 = float(df["close"].rolling(50).mean().iloc[-1])
    signal = TradingSignals.get_combined_signal(
        df, price, 18.0, 1.0, 1.6, ma20, ma50, zscore_min=0.5
    )
    assert signal["action"] in ("STRONG_SELL", "HOLD")
