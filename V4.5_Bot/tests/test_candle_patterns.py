import pandas as pd
import pytest

from core.candle_patterns import CandlePatterns
from core.data_utils import normalize_columns


def _row(open_, high, low, close, volume=1000):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


def frame(rows):
    return pd.DataFrame(rows)


BASE = [
    _row(10, 10.5, 9.5, 10.2),
    _row(10.2, 10.4, 9.8, 10.0),
    _row(10.0, 10.3, 9.7, 10.1),
    _row(10.1, 10.4, 9.9, 10.2),
]


def test_short_frame_is_neutral():
    result = CandlePatterns.identify_all(frame([_row(10, 11, 9, 10.5)]))
    assert result["signal"] == "neutral"
    assert result["strength"] == 0
    assert result["patterns"] == []


def test_hammer_is_bullish():
    df = frame(BASE + [_row(10.0, 10.05, 8.0, 10.04)])
    result = CandlePatterns.identify_all(df)
    assert "鎚頭" in result["patterns"]
    assert result["signal"] == "bullish"
    assert result["entry"] is not None
    assert result["stop"] is not None


def test_shooting_star_is_bearish():
    # Long upper wick, tiny body, no lower wick.
    df = frame(BASE + [_row(10.2, 12.0, 10.2, 10.22)])
    result = CandlePatterns.identify_all(df)
    assert "射擊之星" in result["patterns"]
    assert result["signal"] == "bearish"


def test_bullish_engulfing():
    rows = BASE[:3] + [
        _row(10.5, 10.6, 10.0, 10.1),      # bearish
        _row(9.9, 11.0, 9.8, 10.7),        # engulfs prior body
    ]
    result = CandlePatterns.identify_all(frame(rows))
    assert "看漲吞噬" in result["patterns"]
    assert result["signal"] == "bullish"


def test_bearish_engulfing():
    rows = BASE[:3] + [
        _row(10.0, 10.7, 9.9, 10.6),       # bullish
        _row(10.8, 10.9, 9.7, 9.8),        # engulfs downward
    ]
    result = CandlePatterns.identify_all(frame(rows))
    assert "看跌吞噬" in result["patterns"]
    assert result["signal"] == "bearish"


def test_dragonfly_doji():
    df = frame(BASE + [_row(10.3, 10.32, 8.5, 10.31)])
    result = CandlePatterns.identify_all(df)
    assert "十字星" in result["patterns"]
    assert "（蜻蜓）" in result["patterns"]


def test_gravestone_doji():
    df = frame(BASE + [_row(10.2, 12.0, 10.19, 10.21)])
    result = CandlePatterns.identify_all(df)
    assert "十字星" in result["patterns"]
    assert "（墓碑）" in result["patterns"]


def test_morning_star():
    rows = BASE[:2] + [
        _row(11.0, 11.1, 10.0, 10.1),      # long bearish
        _row(10.05, 10.15, 9.95, 10.06),   # small body
        _row(10.1, 11.2, 10.05, 11.0),     # strong bullish close above midpoint
    ]
    result = CandlePatterns.identify_all(frame(rows))
    assert "晨星" in result["patterns"]
    assert result["signal"] == "bullish"


def test_evening_star():
    rows = BASE[:2] + [
        _row(10.0, 11.2, 9.9, 11.1),       # long bullish
        _row(11.15, 11.25, 11.05, 11.16),  # small body
        _row(11.1, 11.15, 10.0, 10.1),     # strong bearish close below midpoint
    ]
    result = CandlePatterns.identify_all(frame(rows))
    assert "黃昏星" in result["patterns"]
    assert result["signal"] == "bearish"


def test_neutral_when_no_pattern():
    rows = BASE + [_row(10.2, 10.6, 9.9, 10.35)]
    result = CandlePatterns.identify_all(frame(rows))
    assert result["signal"] == "neutral"


def test_strength_is_rounded():
    df = frame(BASE + [_row(10.0, 10.05, 8.0, 10.04)])
    result = CandlePatterns.identify_all(df)
    assert result["strength"] == round(result["strength"], 2)


def test_accepts_normalized_uppercase_input():
    df = frame(BASE + [_row(10.0, 10.05, 8.0, 10.04)]).rename(columns=str.capitalize)
    result = CandlePatterns.identify_all(normalize_columns(df))
    assert result["signal"] in ("bullish", "bearish", "neutral")


def test_result_shape():
    result = CandlePatterns.identify_all(frame(BASE + [_row(10.2, 10.6, 9.9, 10.35)]))
    for key in ("patterns", "signal", "strength", "entry", "stop"):
        assert key in result
