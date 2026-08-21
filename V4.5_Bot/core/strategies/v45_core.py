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

    def prefilter(self, df, context):
        if not context.allow_new_entries and context.regime in ("RISK_OFF", "CRISIS"):
            return False, f"regime {context.regime} blocks new entries"

        z_score = context.quant.get("z_score", 0.0)
        if z_score < context.zscore_min:
            return False, f"Z-Score {z_score:.2f} < 下限 {context.zscore_min}"

        if self.require_structure and None not in (context.ma20, context.ma50):
            if not (context.price > context.ma20 > context.ma50):
                return False, f"結構過濾失敗 (price>{context.ma20:.2f}>{context.ma50:.2f})"

        if context.vol_ratio is not None:
            if not (context.vol_ratio > self.min_vol_ratio_high or context.vol_ratio < self.max_vol_ratio_low):
                return False, f"量比 {context.vol_ratio:.2f} 不符合"

        return True, "OK"

    def generate_signal(self, df, context):
        return TradingSignals.get_combined_signal(
            df,
            context.price,
            context.vix,
            context.quant.get("z_score", 0.0),
            context.vol_ratio if context.vol_ratio is not None else 1.0,
            context.ma20,
            context.ma50,
            zscore_min=context.zscore_min,
        )
