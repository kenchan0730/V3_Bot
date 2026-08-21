from datetime import date, timedelta

import pandas as pd
import pytest

from core.data_utils import (
    detect_price_outlier,
    latest_bar_date,
    normalize_columns,
    previous_trading_day,
    quality_report,
    trading_days_between,
    validate_freshness,
    validate_ohlcv,
)
from tests.conftest import make_ohlcv


@pytest.fixture
def uppercase_ohlcv_df():
    return pd.DataFrame({
        "Open": [10.0, 11.0, 12.0, 13.0, 14.0],
        "High": [11.0, 12.0, 13.0, 14.0, 15.0],
        "Low": [9.0, 10.0, 11.0, 12.0, 13.0],
        "Close": [10.5, 11.5, 12.5, 13.5, 14.5],
        "Volume": [1000, 1100, 1200, 1300, 1400],
    })


# ----- normalization -----

def test_normalize_columns_lowercases_names(uppercase_ohlcv_df):
    result = normalize_columns(uppercase_ohlcv_df)
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]


def test_normalize_columns_is_idempotent(uppercase_ohlcv_df):
    twice = normalize_columns(normalize_columns(uppercase_ohlcv_df))
    assert list(twice.columns) == ["open", "high", "low", "close", "volume"]


def test_normalize_columns_returns_copy(uppercase_ohlcv_df):
    result = normalize_columns(uppercase_ohlcv_df)
    result["close"] = 0
    assert uppercase_ohlcv_df["Close"].iloc[-1] != 0


def test_normalize_columns_multiindex():
    arrays = [["Close", "Close"], ["AAPL", "MSFT"]]
    df = pd.DataFrame([[1.0, 2.0]], columns=pd.MultiIndex.from_arrays(arrays))
    assert "close" in normalize_columns(df).columns


# ----- date helpers -----

def test_latest_bar_date_from_index():
    df = make_ohlcv([10, 11, 12], start="2024-03-01")
    assert latest_bar_date(df) == date(2024, 3, 5)


def test_latest_bar_date_from_column():
    df = pd.DataFrame({"date": ["2024-05-01", "2024-05-02"], "close": [1, 2]})
    assert latest_bar_date(df) == date(2024, 5, 2)


def test_latest_bar_date_empty():
    assert latest_bar_date(pd.DataFrame()) is None


def test_previous_trading_day_skips_weekend():
    monday = date(2024, 3, 4)
    assert previous_trading_day(monday) == date(2024, 3, 1)


def test_trading_days_between_counts_weekdays():
    assert trading_days_between(date(2024, 3, 1), date(2024, 3, 5)) == 2
    assert trading_days_between(date(2024, 3, 5), date(2024, 3, 1)) == 0
    assert trading_days_between(None, date(2024, 3, 1)) == 0


# ----- freshness (H7) -----

def test_validate_freshness_accepts_today():
    today = date.today()
    df = make_ohlcv([10, 11, 12])
    df.index = pd.bdate_range(end=pd.Timestamp(today), periods=3)
    ok, age, _ = validate_freshness(df, reference=today)
    assert ok is True
    assert age == 0


def test_validate_freshness_rejects_stale():
    reference = date(2024, 4, 15)
    df = make_ohlcv([10, 11, 12], start="2024-03-01")
    ok, age, msg = validate_freshness(df, max_age_trading_days=2, reference=reference)
    assert ok is False
    assert age > 2
    assert "過期" in msg


def test_validate_freshness_allows_one_day_lag():
    reference = date(2024, 3, 6)
    df = make_ohlcv([10, 11, 12], start="2024-03-01")
    ok, age, _ = validate_freshness(df, max_age_trading_days=2, reference=reference)
    assert ok is True
    assert age == 1


def test_validate_freshness_no_date():
    ok, age, msg = validate_freshness(pd.DataFrame())
    assert ok is False and age is None and "無法判定" in msg


# ----- structural validation -----

def test_validate_ohlcv_passes(trending_df):
    ok, msg = validate_ohlcv(trending_df, min_bars=60)
    assert ok is True and msg == "OK"


def test_validate_ohlcv_rejects_short():
    ok, msg = validate_ohlcv(make_ohlcv([10, 11]), min_bars=60)
    assert ok is False and "不足" in msg


def test_validate_ohlcv_rejects_empty():
    ok, msg = validate_ohlcv(None)
    assert ok is False and "空" in msg


def test_validate_ohlcv_rejects_missing_column(trending_df):
    ok, msg = validate_ohlcv(trending_df.drop(columns=["volume"]), min_bars=60)
    assert ok is False and "缺少欄位" in msg


def test_validate_ohlcv_rejects_nan(trending_df):
    broken = trending_df.copy()
    broken.iloc[-1, broken.columns.get_loc("close")] = float("nan")
    ok, msg = validate_ohlcv(broken, min_bars=60)
    assert ok is False and "缺失值" in msg


def test_validate_ohlcv_rejects_inconsistent_bar(trending_df):
    broken = trending_df.copy()
    broken.iloc[-1, broken.columns.get_loc("high")] = 0.1
    ok, msg = validate_ohlcv(broken, min_bars=60)
    assert ok is False


# ----- outliers -----

def test_detect_price_outlier_flags_spike(trending_df):
    spiked = trending_df.copy()
    spiked.iloc[-1, spiked.columns.get_loc("close")] = float(spiked["close"].iloc[-2]) * 2
    is_outlier, move = detect_price_outlier(spiked, max_daily_move_pct=40)
    assert is_outlier is True and move > 40


def test_detect_price_outlier_normal(trending_df):
    is_outlier, _ = detect_price_outlier(trending_df, max_daily_move_pct=40)
    assert is_outlier is False


# ----- combined report -----

def test_quality_report_passes(fresh_df):
    report = quality_report(fresh_df, min_bars=60)
    assert report["ok"] is True and report["stage"] == "passed"


def test_quality_report_flags_stale(trending_df):
    reference = date.today() + timedelta(days=400)
    report = quality_report(trending_df, min_bars=60, reference=reference)
    assert report["ok"] is False and report["stage"] == "freshness"


def test_quality_report_flags_structure():
    report = quality_report(make_ohlcv([10, 11]), min_bars=60)
    assert report["ok"] is False and report["stage"] == "structure"


def test_quality_report_flags_outlier(fresh_df):
    spiked = fresh_df.copy()
    last = spiked.columns.get_loc("close")
    spiked.iloc[-1, last] = float(spiked["close"].iloc[-2]) * 3
    spiked.iloc[-1, spiked.columns.get_loc("high")] = spiked.iloc[-1]["close"] + 1
    report = quality_report(spiked, min_bars=60)
    assert report["ok"] is False and report["stage"] == "outlier"
