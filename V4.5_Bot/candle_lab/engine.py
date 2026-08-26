"""Auto-learn pattern forward outcomes from historical OHLCV."""

import logging
from collections import defaultdict

from core.candle_patterns import CandlePatterns

from candle_lab.dataset import fetch_daily
from candle_lab.learner import save_stats

logger = logging.getLogger(__name__)


class CandleLabEngine:
    """Scan history, measure pattern forward returns, export stats for bot + trader."""

    def __init__(self, config=None):
        cfg = (config or {}).get("candle", {}) or {}
        self.forward_bars = int(cfg.get("learn_forward_bars", 10))
        self.warmup_bars = int(cfg.get("learn_warmup_bars", 60))
        self.min_samples = int(cfg.get("min_learned_samples", 8))
        self.period = cfg.get("learn_period", "6mo")

    def auto_learn(self, symbols, save=True):
        """Pull history for each symbol and aggregate pattern win rates."""
        aggregate = defaultdict(lambda: {"wins": 0, "total": 0, "sum_return_pct": 0.0})
        per_symbol = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "total": 0, "sum_return_pct": 0.0}))
        scanned = 0

        for symbol in symbols:
            df = fetch_daily(symbol, period=self.period)
            if df is None or len(df) < self.warmup_bars + self.forward_bars + 5:
                logger.warning(f"{symbol} 数据不足，跳过 Candle Lab 学习")
                continue
            scanned += 1
            self._scan_symbol(df, symbol, aggregate, per_symbol)

        patterns = self._finalize_stats(aggregate, per_symbol)
        result = {
            "symbols_scanned": scanned,
            "forward_bars": self.forward_bars,
            "patterns": patterns,
        }
        if save:
            save_stats(patterns)
        logger.info(
            f"Candle Lab 完成：{scanned} 只股票，"
            f"{len(patterns)} 条形态统计（forward={self.forward_bars} bars）"
        )
        return result

    def _scan_symbol(self, df, symbol, aggregate, per_symbol):
        end = len(df) - self.forward_bars
        for index in range(self.warmup_bars, end):
            window = df.iloc[: index + 1]
            candle = CandlePatterns.identify_all(window)
            driver = candle.get("driver")
            signal = candle.get("signal")
            strength = candle.get("strength", 0) or 0
            if not driver or signal not in ("bullish", "bearish"):
                continue

            entry_close = float(window.iloc[-1]["close"])
            future_close = float(df.iloc[index + self.forward_bars]["close"])
            if entry_close <= 0:
                continue
            ret_pct = (future_close - entry_close) / entry_close * 100.0

            if signal == "bullish":
                win = ret_pct > 0
            else:
                win = ret_pct < 0

            for bucket, key in ((aggregate, driver), (per_symbol[symbol], driver)):
                bucket[key]["total"] += 1
                bucket[key]["sum_return_pct"] += ret_pct
                if win:
                    bucket[key]["wins"] += 1

    def _finalize_stats(self, aggregate, per_symbol):
        patterns = {}
        for name, data in aggregate.items():
            total = data["total"]
            if total == 0:
                continue
            patterns[name] = {
                "wins": data["wins"],
                "total": total,
                "win_rate": round(data["wins"] / total, 3),
                "avg_return_pct": round(data["sum_return_pct"] / total, 2),
                "by_symbol": {},
            }

        for symbol, drivers in per_symbol.items():
            for name, data in drivers.items():
                if name not in patterns:
                    continue
                total = data["total"]
                if total < 3:
                    continue
                patterns[name]["by_symbol"][symbol] = {
                    "wins": data["wins"],
                    "total": total,
                    "win_rate": round(data["wins"] / total, 3),
                    "avg_return_pct": round(data["sum_return_pct"] / total, 2),
                }
        return patterns

    def report_text(self, stats=None):
        """Human-readable weekly-style report for CLI / logs."""
        from candle_lab.learner import load_stats, top_weak_spots

        if stats is None:
            stats = load_stats().get("patterns", {})
        if not stats:
            return "尚无学习统计。运行: python -m candle_lab learn"

        lines = ["=== Candle Lab 形态胜率报告 ===", ""]
        ranked = sorted(stats.items(), key=lambda kv: kv[1].get("win_rate", 0), reverse=True)
        for name, data in ranked:
            wr = data.get("win_rate", 0) * 100
            flag = "✅" if wr >= 50 else ("⚠️" if wr >= 40 else "❌")
            lines.append(
                f"{flag} {name}: 胜率 {wr:.0f}% ({data['wins']}/{data['total']}) "
                f"| 均回报 {data.get('avg_return_pct', 0):+.1f}% @ {self.forward_bars} bars"
            )
            for sym, sym_data in (data.get("by_symbol") or {}).items():
                swr = sym_data["win_rate"] * 100
                lines.append(
                    f"    └ {sym}: {swr:.0f}% ({sym_data['wins']}/{sym_data['total']})"
                )

        weak = top_weak_spots()
        if weak:
            lines.append("")
            lines.append("你的 Quiz 弱项：" + ", ".join(f"{n}({c}次)" for n, c in weak))
        return "\n".join(lines)
