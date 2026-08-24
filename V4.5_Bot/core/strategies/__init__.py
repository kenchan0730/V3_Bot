"""Strategy registry: map config names to strategy classes."""

import logging

from core.strategies.base import BaseStrategy, MarketContext
from core.strategies.v45_core import V45CoreStrategy

logger = logging.getLogger(__name__)

REGISTRY = {
    "v45_core": V45CoreStrategy,
}


def register(name, strategy_cls):
    if not issubclass(strategy_cls, BaseStrategy):
        raise TypeError(f"{strategy_cls} 必須繼承 BaseStrategy")
    REGISTRY[name] = strategy_cls


def load_strategies(config=None):
    """Instantiate strategies listed in config; defaults to v45_core."""
    entries = (config or {}).get("strategies") or [{"name": "v45_core", "enabled": True}]
    candle_cfg = (config or {}).get("candle", {}) or {}
    swing_cfg = (config or {}).get("swing_trading", {}) or {}
    loaded = []
    for entry in entries:
        if isinstance(entry, str):
            entry = {"name": entry, "enabled": True}
        name = entry.get("name")
        strategy_cls = REGISTRY.get(name)
        if strategy_cls is None:
            logger.error(f"未知策略 '{name}'，已略過")
            continue
        strategy_config = {**entry, "_root_candle": candle_cfg, "_root_swing": swing_cfg}
        strategy = strategy_cls(strategy_config)
        if not strategy.enabled:
            logger.info(f"策略 {name} 已停用")
            continue
        loaded.append(strategy)

    if not loaded:
        logger.warning("未載入任何策略，回退至 v45_core")
        loaded.append(V45CoreStrategy({}))
    logger.info(f"已載入策略: {[s.name for s in loaded]}")
    return loaded


__all__ = ["BaseStrategy", "MarketContext", "V45CoreStrategy", "load_strategies", "register", "REGISTRY"]
