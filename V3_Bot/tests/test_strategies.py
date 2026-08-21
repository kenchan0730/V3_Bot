import pytest

from core.strategies import REGISTRY, MarketContext, load_strategies, register
from core.strategies.base import BaseStrategy
from core.strategies.v45_core import V45CoreStrategy
from core.quant_engine import QuantEngine


def build_context(df, **overrides):
    price = float(df["close"].iloc[-1])
    quant = QuantEngine.dynamic_score(df)
    defaults = {
        "symbol": "TEST",
        "price": price,
        "vix": 18.0,
        "zscore_min": 0.5,
        "quant": quant,
        "vol_ratio": 1.7,
        "ma20": float(df["close"].rolling(20).mean().iloc[-1]),
        "ma50": float(df["close"].rolling(50).mean().iloc[-1]),
    }
    defaults.update(overrides)
    return MarketContext(**defaults)


def test_registry_contains_default():
    assert "v45_core" in REGISTRY


def test_load_strategies_default():
    strategies = load_strategies({})
    assert len(strategies) == 1
    assert strategies[0].name == "v45_core"


def test_load_strategies_from_config():
    strategies = load_strategies({"strategies": [{"name": "v45_core", "enabled": True}]})
    assert strategies[0].name == "v45_core"


def test_load_strategies_accepts_string_entries():
    strategies = load_strategies({"strategies": ["v45_core"]})
    assert strategies[0].name == "v45_core"


def test_load_strategies_skips_disabled_and_falls_back():
    strategies = load_strategies({"strategies": [{"name": "v45_core", "enabled": False}]})
    assert len(strategies) == 1  # fallback


def test_load_strategies_ignores_unknown():
    strategies = load_strategies({"strategies": [{"name": "does_not_exist"}]})
    assert strategies[0].name == "v45_core"


def test_register_rejects_non_strategy():
    with pytest.raises(TypeError):
        register("bad", dict)


def test_register_custom_strategy(trending_df):
    class AlwaysHold(BaseStrategy):
        name = "always_hold"

        def generate_signal(self, df, context):
            return {"action": "HOLD", "reason": "custom"}

    register("always_hold", AlwaysHold)
    strategies = load_strategies({"strategies": [{"name": "always_hold"}]})
    signal = strategies[0].generate_signal(trending_df, build_context(trending_df))
    assert signal["reason"] == "custom"
    REGISTRY.pop("always_hold", None)


def test_base_strategy_is_abstract():
    with pytest.raises(TypeError):
        BaseStrategy()


def test_prefilter_blocks_low_zscore(trending_df):
    strategy = V45CoreStrategy({})
    context = build_context(trending_df, quant={"z_score": 0.1, "rsi": 50})
    ok, reason = strategy.prefilter(trending_df, context)
    assert ok is False and "Z-Score" in reason


def test_prefilter_blocks_broken_structure(trending_df):
    strategy = V45CoreStrategy({})
    context = build_context(trending_df, quant={"z_score": 1.0}, ma20=999.0, ma50=1000.0)
    ok, reason = strategy.prefilter(trending_df, context)
    assert ok is False and "結構" in reason


def test_prefilter_blocks_bad_volume_ratio(trending_df):
    strategy = V45CoreStrategy({})
    context = build_context(trending_df, quant={"z_score": 1.0}, vol_ratio=1.0)
    ok, reason = strategy.prefilter(trending_df, context)
    assert ok is False and "量比" in reason


def test_prefilter_passes_valid_setup(trending_df):
    strategy = V45CoreStrategy({})
    context = build_context(trending_df, quant={"z_score": 1.0}, vol_ratio=1.7)
    ok, reason = strategy.prefilter(trending_df, context)
    assert ok is True and reason == "OK"


def test_prefilter_can_disable_structure(trending_df):
    strategy = V45CoreStrategy({"require_structure": False})
    context = build_context(trending_df, quant={"z_score": 1.0}, ma20=999.0, ma50=1000.0, vol_ratio=1.7)
    ok, _ = strategy.prefilter(trending_df, context)
    assert ok is True


def test_generate_signal_returns_action(trending_df):
    strategy = V45CoreStrategy({})
    signal = strategy.generate_signal(trending_df, build_context(trending_df))
    assert signal["action"] in ("STRONG_BUY", "STRONG_SELL", "HOLD")


def test_strategy_repr():
    assert "v45_core" in repr(V45CoreStrategy({}))
