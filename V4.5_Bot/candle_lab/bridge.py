"""Read-only bridge: learned stats → live bot candle conviction adjustment.

Does NOT change CandlePatterns detection rules — only scales or blocks the
strength used by TradingSignals when historical win rate is poor.
"""

import logging

from candle_lab.learner import load_stats

logger = logging.getLogger(__name__)


def reliability_multiplier(symbol, pattern_driver, candle_cfg, stats_payload=None):
    """Return strength multiplier in [0, 1.2] from learned win rates."""
    cfg = candle_cfg or {}
    if not cfg.get("use_learned_stats", False):
        return 1.0, None

    min_samples = int(cfg.get("min_learned_samples", 8))
    min_win_rate = float(cfg.get("min_learned_win_rate", 0.40))
    stats_payload = stats_payload or load_stats()
    patterns = stats_payload.get("patterns", {})
    if not pattern_driver or pattern_driver not in patterns:
        return 1.0, None

    entry = patterns[pattern_driver]
    sym_stats = (entry.get("by_symbol") or {}).get(symbol)
    if sym_stats and sym_stats.get("total", 0) >= max(3, min_samples // 2):
        win_rate = sym_stats["win_rate"]
        source = f"{symbol}:{pattern_driver}"
        samples = sym_stats["total"]
    elif entry.get("total", 0) >= min_samples:
        win_rate = entry["win_rate"]
        source = f"global:{pattern_driver}"
        samples = entry["total"]
    else:
        return 1.0, None

    if win_rate < min_win_rate:
        return 0.0, f"{source} 胜率 {win_rate:.0%} < {min_win_rate:.0%}（n={samples}）"
    if win_rate < 0.45:
        return 0.75, f"{source} 胜率偏低 {win_rate:.0%}，缩仓 candle 权重"
    if win_rate >= 0.55:
        return 1.1, f"{source} 胜率 {win_rate:.0%}，加强 candle 权重"
    return 1.0, None


def apply_learned_adjustment(candle, symbol, candle_cfg=None, stats_payload=None):
    """Adjust candle dict in-place copy; may neutralize weak learned patterns."""
    driver = candle.get("driver")
    if not driver:
        return candle

    mult, reason = reliability_multiplier(symbol, driver, candle_cfg, stats_payload)
    if mult == 1.0 and reason is None:
        return candle

    adjusted = dict(candle)
    adjusted["learned_driver"] = driver
    adjusted["learned_reason"] = reason

    if mult == 0.0:
        adjusted["strength"] = 0
        adjusted["signal"] = "neutral"
        adjusted["learned_blocked"] = True
        logger.info(f"🕯️ Candle Lab 阻止弱形态 {driver} ({symbol}): {reason}")
        return adjusted

    strength = float(adjusted.get("strength", 0) or 0)
    adjusted["strength"] = round(strength * mult, 2)
    adjusted["learned_multiplier"] = mult
    if reason:
        logger.debug(f"🕯️ Candle Lab 调整 {driver} ({symbol}): x{mult} — {reason}")
    return adjusted
