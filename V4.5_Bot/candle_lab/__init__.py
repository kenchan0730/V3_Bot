"""K-line / candlestick learning lab — auto stats + trader education.

Read-only bridge into the live bot: learned win rates can adjust candle
conviction when ``candle.use_learned_stats`` is enabled in config.yaml.
"""

from candle_lab.bridge import apply_learned_adjustment, load_stats
from candle_lab.engine import CandleLabEngine

__all__ = ["CandleLabEngine", "apply_learned_adjustment", "load_stats"]
