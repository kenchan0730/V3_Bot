#!/usr/bin/env python3
"""Grid-search QuantEngine factor weights against realised backtest metrics.

The shipped 35/25/20/20 split is an engineering prior, not a fitted result.
This script measures how sensitive profit factor / return / drawdown are to the
weights so the default can be defended with evidence (or replaced).

Usage:
    python scripts/factor_sensitivity.py --symbols AVAH,QXO --period 2y
    python scripts/factor_sensitivity.py --symbols AVAH --step 0.1 --json
"""

import argparse
import itertools
import json
import logging
import sys

import yfinance as yf

from backtest.engine import BacktestEngine
from core.config_loader import load_config
from core.quant_engine import DEFAULT_WEIGHTS, QuantEngine

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")

FACTORS = ("momentum", "volume", "volatility", "relative_strength")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="因子權重敏感度分析")
    parser.add_argument("--symbols", default="", help="逗號分隔；預設用 config watchlist")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--capital", type=float, default=1275.0)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--step", type=float, default=0.15, help="權重掃描步長")
    parser.add_argument("--top", type=int, default=10, help="輸出前 N 組")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def weight_grid(step):
    """Every weight combination on the simplex, rounded to ``step``."""
    levels = [round(i * step, 4) for i in range(int(1 / step) + 1)]
    grid = []
    for combo in itertools.product(levels, repeat=len(FACTORS)):
        total = sum(combo)
        if total <= 0 or abs(total - 1.0) > 1e-6:
            continue
        grid.append(dict(zip(FACTORS, combo)))
    return grid


def load_history(symbols, period):
    frames = {}
    for symbol in symbols:
        df = yf.download(symbol, period=period, interval="1d", progress=False)
        if df is None or df.empty or len(df) < 130:
            print(f"{symbol}: 數據不足（需 >=130 根以啟用波動率因子），略過")
            continue
        frames[symbol] = df
    return frames


def evaluate(config, frames, weights, capital):
    """Aggregate backtest metrics across symbols for one weight set."""
    scoped = dict(config)
    scoped["zscore"] = {**(config.get("zscore") or {}), "weights": weights}

    engine = BacktestEngine(scoped, initial_capital=capital)
    trades = wins = 0
    gross_win = gross_loss = 0.0
    returns = []
    worst_dd = 0.0

    for symbol, df in frames.items():
        result = engine.run(symbol, df)
        trades += len(result.trades)
        wins += len(result.wins)
        gross_win += sum(t["pnl"] for t in result.wins)
        gross_loss += abs(sum(t["pnl"] for t in result.losses))
        returns.append(result.total_return_pct)
        worst_dd = max(worst_dd, result.max_drawdown_pct)

    profit_factor = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    return {
        "weights": weights,
        "trades": trades,
        "win_rate_pct": round(wins / trades * 100, 2) if trades else 0.0,
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else "inf",
        "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else 0.0,
        "max_drawdown_pct": round(worst_dd, 2),
    }


def sort_key(row):
    pf = row["profit_factor"]
    pf = 1e9 if pf == "inf" else float(pf)
    return (pf, row["avg_return_pct"], -row["max_drawdown_pct"])


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        watchlist = config.get("watchlist", {})
        if isinstance(watchlist, dict):
            symbols = list(watchlist.get("core") or [])
        else:
            symbols = list(watchlist or [])
    if not symbols:
        print("未指定標的")
        return 1

    frames = load_history(symbols, args.period)
    if not frames:
        print("沒有可用數據")
        return 1

    grid = weight_grid(args.step)
    print(f"掃描 {len(grid)} 組權重 × {len(frames)} 檔標的 ...")

    rows = [evaluate(config, frames, weights, args.capital) for weights in grid]
    baseline = evaluate(config, frames, dict(DEFAULT_WEIGHTS), args.capital)
    rows.sort(key=sort_key, reverse=True)
    top = rows[: args.top]

    if args.json:
        print(json.dumps({"baseline": baseline, "top": top}, indent=2))
        return 0

    print("\n=== 現行預設 (35/25/20/20) ===")
    for key, value in baseline.items():
        print(f"  {key:<20} {value}")

    print(f"\n=== 前 {len(top)} 組 ===")
    for row in top:
        weights = " ".join(f"{k[:3]}={v:.2f}" for k, v in row["weights"].items())
        print(
            f"  PF={row['profit_factor']:<6} ret={row['avg_return_pct']:>7}% "
            f"dd={row['max_drawdown_pct']:>6}% n={row['trades']:<4} {weights}"
        )

    spread = [r for r in rows if r["profit_factor"] != "inf"]
    if spread:
        best = float(spread[0]["profit_factor"])
        worst = float(spread[-1]["profit_factor"])
        print(
            f"\n敏感度: profit factor 在 {worst:.2f} – {best:.2f} 之間變動。"
            f"\n若區間很窄，代表權重不是主要驅動因子（策略對權重不敏感）；"
            f"\n若區間很寬，現行 35/25/20/20 需要實證支持才能繼續使用。"
        )

    normalised = QuantEngine.resolve_weights(config.get("zscore", {}).get("weights"))
    print(f"\nconfig.yaml 目前生效權重: {normalised}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
