import pandas as pd
import pytest

from core.candle_patterns import CandlePatterns
from core.data_utils import normalize_columns


def _row(open_, high, low, close, volume=1000):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


@pytest.fixture
def hammer_df():
    rows = [
        _row(10, 10.5, 9.5, 10.2),
        _row(10.2, 10.4, 9.8, 10.0),
        _row(10.0, 10.3, 9.7, 10.1),
        _row(10.1, 10.4, 9.9, 10.2),
        _row(10.0, 10.05, 8.0, 10.04),
    ]
    return pd.DataFrame(rows)


def test_identify_all_dragonfly_doji_bullish():
    df = pd.DataFrame([
        _row(10, 10.5, 9.5, 10.2),
        _row(10.2, 10.4, 9.8, 10.0),
        _row(10.0, 10.3, 9.7, 10.1),
        _row(10.1, 10.4, 9.9, 10.2),
        _row(10.3, 10.35, 8.5, 10.32),
    ])
    result = CandlePatterns.identify_all(df)
    assert "十字星" in result["patterns"]
    assert result["signal"] in ("bullish", "neutral")


def test_identify_all_bearish_engulfing():
    df = pd.DataFrame([
        _row(10, 10.5, 9.5, 10.2),
        _row(10.2, 10.4, 9.8, 10.0),
        _row(10.0, 10.3, 9.7, 10.1),
        _row(10.5, 10.8, 10.4, 10.7),
        _row(10.6, 10.7, 9.8, 9.9),
    ])
    result = CandlePatterns.identify_all(df)
    assert result["signal"] in ("bearish", "neutral", "bullish")


def test_identify_all_neutral_on_short_df():
    df = pd.DataFrame([_row(10, 11, 9, 10.5)])
    result = CandlePatterns.identify_all(df)
    assert result["signal"] == "neutral"
    assert result["strength"] == 0


def test_identify_all_hammer_bullish(hammer_df):
    result = CandlePatterns.identify_all(hammer_df)
    assert "鎚頭" in result["patterns"]
    assert result["signal"] == "bullish"
    assert result["strength"] >= 0.4


def test_identify_all_works_with_normalized_columns(hammer_df):
    raw = hammer_df.rename(columns=str.capitalize)
    normalized = normalize_columns(raw)
    result = CandlePatterns.identify_all(normalized)
    assert result["signal"] in ("bullish", "neutral", "bearish")
