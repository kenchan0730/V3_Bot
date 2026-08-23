"""Factor weights must come from config, and the volatility factor must be observable.

The audit found config.yaml declaring `zscore.weights` while the engine used
hard-coded constants, and the 20%-weighted volatility factor silently reading
0.0 on short history.
"""

import pytest

from core.quant_engine import (
    DEFAULT_WEIGHTS,
    MIN_BARS_FOR_VOLATILITY,
    QuantEngine,
)
from tests.helpers import make_ohlcv


def test_default_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_resolve_weights_defaults():
    assert QuantEngine.resolve_weights(None) == pytest.approx(DEFAULT_WEIGHTS)


def test_resolve_weights_renormalises():
    resolved = QuantEngine.resolve_weights({
        "momentum": 2.0, "volume": 2.0, "volatility": 2.0, "relative_strength": 2.0,
    })
    assert sum(resolved.values()) == pytest.approx(1.0)
    for value in resolved.values():
        assert value == pytest.approx(0.25)


def test_resolve_weights_partial_override():
    resolved = QuantEngine.resolve_weights({"momentum": 0.7})
    assert sum(resolved.values()) == pytest.approx(1.0)
    assert resolved["momentum"] > resolved["volume"]


def test_resolve_weights_rejects_garbage():
    resolved = QuantEngine.resolve_weights({"momentum": "abc", "volume": -5})
    assert sum(resolved.values()) == pytest.approx(1.0)
    assert resolved["volume"] == 0.0


def test_resolve_weights_all_zero_falls_back():
    resolved = QuantEngine.resolve_weights(dict.fromkeys(DEFAULT_WEIGHTS, 0.0))
    assert resolved == pytest.approx(DEFAULT_WEIGHTS)


def _trending(n):
    return make_ohlcv([10 + i * 0.05 for i in range(n)])


def test_weights_change_the_score():
    df = _trending(140)
    momentum_heavy = QuantEngine.dynamic_score(df, weights={
        "momentum": 1.0, "volume": 0.0, "volatility": 0.0, "relative_strength": 0.0,
    })
    volume_heavy = QuantEngine.dynamic_score(df, weights={
        "momentum": 0.0, "volume": 1.0, "volatility": 0.0, "relative_strength": 0.0,
    })
    assert momentum_heavy["z_score"] != volume_heavy["z_score"]
    assert momentum_heavy["weights"]["momentum"] == pytest.approx(1.0)


def test_volatility_factor_not_computable_on_short_history():
    """3 months of bars left the 20%-weighted factor permanently at zero."""
    result = QuantEngine.dynamic_score(_trending(90))
    assert result["volatility_factor_active"] is False
    assert result["z_volatility"] == 0.0
    assert "volatility" not in result["factors_active"]


def test_volatility_factor_computable_with_six_months():
    result = QuantEngine.dynamic_score(_trending(MIN_BARS_FOR_VOLATILITY + 40))
    assert result["volatility_factor_active"] is True


def test_volatility_factor_contributes_on_varying_volatility():
    closes = []
    for block in range(14):
        amplitude = 0.05 if block % 2 == 0 else 0.9
        closes += [20 + amplitude * ((i % 5) - 2) + block * 0.4 for i in range(15)]
    result = QuantEngine.dynamic_score(make_ohlcv(closes))
    assert result["volatility_factor_active"] is True
    assert result["z_volatility"] != 0.0
    assert "volatility" in result["factors_active"]


def test_score_reports_weights_and_active_factors():
    result = QuantEngine.dynamic_score(_trending(140))
    assert set(result["weights"]) == set(DEFAULT_WEIGHTS)
    assert isinstance(result["factors_active"], list)


def test_compression_series_matches_loop_reference():
    """Vectorised compression must equal the original per-bar loop."""
    df = make_ohlcv([10 + (i % 9) * 0.3 for i in range(150)])
    high, low = df["high"], df["low"]
    vectorised, _ = QuantEngine.compression_series(high, low)

    for i in (60, 100, 149):
        atr_short = float(high.iloc[i - 13:i + 1].max()) - float(low.iloc[i - 13:i + 1].min())
        atr_long = float(high.iloc[i - 49:i + 1].max()) - float(low.iloc[i - 49:i + 1].min())
        ratio = atr_short / atr_long if atr_long > 0 else 1.0
        if ratio <= 0.85:
            expected = 1.5
        elif ratio >= 1.3:
            expected = -1.5
        else:
            expected = (1.3 - ratio) / (1.3 - 0.85) * 1.5 - 1.5
        assert vectorised.iloc[i] == pytest.approx(expected)


def test_short_frame_still_reports_weights():
    result = QuantEngine.dynamic_score(make_ohlcv([10, 11, 12]))
    assert result["weights"] == pytest.approx(DEFAULT_WEIGHTS)
    assert result["factors_active"] == []
