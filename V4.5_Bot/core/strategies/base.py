"""Strategy plugin contract.

A strategy receives validated, lowercase-column OHLCV data plus market context
and returns a signal dict compatible with the existing V4.5 shape:

    {"action": "STRONG_BUY" | "STRONG_SELL" | "HOLD", "entry", "stop",
     "target1", "target2", "confidence", "reason"}
"""

from abc import ABC, abstractmethod


class MarketContext:
    """Context passed to every strategy evaluation."""

    def __init__(self, symbol, price, vix=18.0, zscore_min=0.5, exposure=100,
                 breadth_score=None, quant=None, vol_ratio=None, ma20=None, ma50=None):
        self.symbol = symbol
        self.price = price
        self.vix = vix
        self.zscore_min = zscore_min
        self.exposure = exposure
        self.breadth_score = breadth_score
        self.quant = quant or {}
        self.vol_ratio = vol_ratio
        self.ma20 = ma20
        self.ma50 = ma50


class BaseStrategy(ABC):
    """Subclass and register in config.yaml under ``strategies``."""

    name = "base"

    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.weight = float(self.config.get("weight", 1.0))

    @abstractmethod
    def generate_signal(self, df, context):
        """Return a signal dict for the given data and context."""

    def prefilter(self, df, context):
        """Optional cheap gate before generate_signal. Return (ok, reason)."""
        return True, "OK"

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name} enabled={self.enabled}>"


HOLD_SIGNAL = {"action": "HOLD", "reason": "策略未產生信號"}
