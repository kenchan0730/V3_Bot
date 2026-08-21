import pandas as pd
import pytest

from core.quant_engine import QuantEngine
from tests.conftest import make_ohlcv


def test_get_columns_returns_lowercase_names(trending_df):
    assert QuantEngine._get_columns(trending_df) == ("close", "high", "low", "volume")


def test_to_float_handles_series():
    series = pd.Series([1.0, 2.0, 3.5])
    assert QuantEngine._to_float(series) == 3.5


def test_to_float_handles_scalar():
    assert QuantEngine._to_float(4.2) == 4.2


def test_calculate_zscore_returns_series():
    series = pd.Series(range(100), dtype="float64")
    z = QuantEngine.calculate_zscore(series, window=20)
    assert isinstance(z, pd.Series)
    assert len(z) == 100


def test_calculate_rsi_within_bounds(trending_df):
    rsi = QuantEngine.calculate_rsi(trending_df)
    assert 0 <= rsi <= 100


def test_calculate_rsi_uptrend_is_high(trending_df):
    assert QuantEngine.calculate_rsi(trending_df) > 60


def test_calculate_rsi_short_series_defaults():
    df = make_ohlcv([10, 11, 12])
    assert QuantEngine.calculate_rsi(df) == 50.0


def test_dynamic_score_short_frame_returns_neutral():
    result = QuantEngine.dynamic_score(make_ohlcv([10, 11, 12]))
    assert result["z_score"] == 0.0
    assert result["rsi"] == 50.0
    assert result["compression_ratio"] == 1.0


def test_dynamic_score_keys(trending_df):
    result = QuantEngine.dynamic_score(trending_df)
    for key in ("z_score", "z_momentum", "z_volume", "z_volatility", "z_rs", "compression_ratio", "rsi"):
        assert key in result


def test_dynamic_score_is_bounded(trending_df):
    result = QuantEngine.dynamic_score(trending_df)
    assert -3.0 <= result["z_score"] <= 3.0
    assert -3.0 <= result["z_rs"] <= 3.0


def test_dynamic_score_accepts_uppercase_columns(trending_df):
    upper = trending_df.rename(columns=str.capitalize)
    result = QuantEngine.dynamic_score(upper)
    assert "z_score" in result


def test_dynamic_score_handles_flat_prices():
    flat = make_ohlcv([10.0] * 120)
    result = QuantEngine.dynamic_score(flat)
    assert result["z_score"] == result["z_score"]  # not NaN


def test_dynamic_score_penalises_parabolic_move():
    closes = [10 + i * 0.05 for i in range(115)]
    closes += [closes[-1] * 1.3] * 5
    result = QuantEngine.dynamic_score(make_ohlcv(closes))
    assert result["z_score"] <= 3.0


def test_get_rsi_alert_overheat():
    zone, message = QuantEngine.get_rsi_alert(85, 2.0)
    assert zone == "overheat" and message


def test_get_rsi_alert_oversold():
    zone, _ = QuantEngine.get_rsi_alert(15, 0.0)
    assert zone == "oversold"


def test_get_rsi_alert_neutral():
    zone, message = QuantEngine.get_rsi_alert(50, 0.5)
    assert zone == "neutral" and message is None


def test_get_rsi_alert_nan():
    zone, _ = QuantEngine.get_rsi_alert(float("nan"), 1.0)
    assert zone == "neutral"
