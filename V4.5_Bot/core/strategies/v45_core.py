"""Default V4.5 strategy: preserves the original quant + candle signal logic."""

import logging

from core.strategies.base import BaseStrategy
from core.trading_signals import TradingSignals

logger = logging.getLogger(__name__)


class V45CoreStrategy(BaseStrategy):
    """Wraps TradingSignals/QuantEngine without altering their behaviour."""

    name = "v45_core"

    def __init__(self, config=None):
        super().__init__(config)
        self.require_structure = bool(self.config.get("require_structure", True))
        self.min_vol_ratio_high = float(self.config.get("min_vol_ratio_high", 1.5))
        self.max_vol_ratio_low = float(self.config.get("max_vol_ratio_low", 0.8))
        swing = (self.config.get("_root_swing") or {}) if isinstance(self.config, dict) else {}
        if swing:
            self.trend_mode = swing.get("trend_mode", "swing")
        else:
            self.trend_mode = "full" if self.require_structure else "off"

    def prefilter(self, df, context):
        if not context.allow_new_entries and context.regime in ("RISK_OFF", "CRISIS"):
            return False, f"regime {context.regime} blocks new entries"

        z_score = context.quant.get("z_score", 0.0)
        if z_score < context.zscore_min:
            return False, f"Z-Score {z_score:.2f} < 下限 {context.zscore_min}"

        if self.require_structure and None not in (context.ma20, context.ma50):
            if not (context.price > context.ma20 > context.ma50):
                return False, f"結構過濾失敗 (price>{context.ma20:.2f}>{context.ma50:.2f})"
        elif self.trend_mode == "swing" and context.ma50:
            if context.price <= context.ma50:
                return False, f"Swing 趨勢: 價格 {context.price:.2f} <= MA50 {context.ma50:.2f}"

        if context.vol_ratio is not None:
            overrides = getattr(context, "threshold_overrides", None) or {}
            min_vol_high = float(overrides.get("min_vol_ratio_high", self.min_vol_ratio_high))
            soft_vol = max(1.0, min_vol_high - 0.15)
            if not (context.vol_ratio > soft_vol or context.vol_ratio < self.max_vol_ratio_low):
                return False, f"量比 {context.vol_ratio:.2f} 不符合"

        return True, "OK"

    def generate_signal(self, df, context):
        candle_cfg = dict((self.config.get("_root_candle") or {}) if isinstance(self.config, dict) else {})
        swing_cfg = dict((self.config.get("_root_swing") or {}) if isinstance(self.config, dict) else {})

        # Pace-adjusted thresholds win over static config for the soft gates.
        overrides = getattr(context, "threshold_overrides", None) or {}
        for key in ("moderate_min_edges", "moderate_min_confluence", "zscore_max"):
            if key in overrides:
                swing_cfg[key] = overrides[key]
        candle_cfg["_swing"] = swing_cfg

        min_strength = float(overrides.get("min_candle_strength", candle_cfg.get("min_strength", 0.4)))
        zmax = float(swing_cfg.get("zscore_max", 1.45))
        min_vol_high = float(overrides.get("min_vol_ratio_high", self.min_vol_ratio_high))
        return TradingSignals.get_combined_signal(
            df,
            context.price,
            context.vix,
            context.quant.get("z_score", 0.0),
            context.vol_ratio if context.vol_ratio is not None else 1.0,
            context.ma20,
            context.ma50,
            zscore_min=context.zscore_min,
            min_candle_strength=min_strength,
            min_vol_ratio_high=min_vol_high,
            max_vol_ratio_low=self.max_vol_ratio_low,
            trend_mode=self.trend_mode,
            zscore_max=zmax,
            moderate_enabled=bool(swing_cfg.get("moderate_buy_enabled", True)),
            moderate_min_edges=int(swing_cfg.get("moderate_min_edges", 4)),
            moderate_min_confluence=int(swing_cfg.get("moderate_min_confluence", 5)),
            symbol=context.symbol,
            candle_config=candle_cfg,
            trigger_config=(
                (self.config.get("_root_triggers") or {}) if isinstance(self.config, dict) else {}
            ),
        )
