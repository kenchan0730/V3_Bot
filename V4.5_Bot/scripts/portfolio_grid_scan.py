#!/usr/bin/env python3
"""Grid-scan risk % and concentration cap on portfolio-level replay.

Avoids overfitting a single 2y window by defaulting to 5y; train on first 3y
and report hold-out on last 2y when --split is set.

Usage:
    python scripts/portfolio_grid_scan.py --period 5y --capital 1275
    python scripts/portfolio_grid_scan.py --split --top 15
"""

import argparse
import itertools
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import yfinance as yf

from backtest.portfolio_engine import PortfolioBacktestEngine
from backtest.main import build_mind, watchlist_symbols
from core.config_loader import load_config

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="組合倉位/風險 grid 掃描")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--period", default="5y")
    parser.add_argument("--capital", type=float, default=1275.0)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--risk-grid", default="1.5,2.0,2.5,3.0")
    parser.add_argument("--symbol-pct-grid", default="25,33,40,50")
    parser.add_argument("--target-r-grid", default="1.5,2.0,2.5,3.0,4.0")
    parser.add_argument("--split", action="store_true", help="3y 訓練 + 2y 樣本外")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def parse_float_list(text):
    return [float(x.strip()) for x in text.split(",") if x.strip()]


def load_frames(symbols, period):
    frames = {}
    for symbol in symbols:
        df = yf.download(symbol, period=period, interval="1d", progress=False)
        if df is None or df.empty or len(df) < 200:
            continue
        frames[symbol] = df
    return frames


def slice_frames(frames, start=None, end=None):
    out = {}
    for symbol, df in frames.items():
        if not isinstance(df.index, pd.DatetimeIndex):
            df = df.copy()
            df.index = pd.to_datetime(df.index)
        sub = df
        if start is not None:
            sub = sub.loc[sub.index >= pd.Timestamp(start)]
        if end is not None:
            sub = sub.loc[sub.index <= pd.Timestamp(end)]
        if len(sub) >= 120:
            out[symbol] = sub
    return out


def evaluate(config, frames, capital, vix_df, mind):
    engine = PortfolioBacktestEngine(
        config, initial_capital=capital, professional_mind=mind,
    )
    result = engine.run_portfolio(frames, vix_df=vix_df)
    s = result.summary()
    return {
        "return_pct": s["total_return_pct"],
        "trades": s["trades"],
        "win_rate": s["win_rate_pct"],
        "pf": s["profit_factor"],
        "max_dd": s["max_drawdown_pct"],
        "trades_per_month": s["trades_per_month"],
        "costs": s["total_costs"],
        "throttles": s.get("throttle_stats"),
    }


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or watchlist_symbols(config)
    frames = load_frames(symbols, args.period)
    if not frames:
        print("無可用數據")
        return 1

    vix = yf.download("^VIX", period=args.period, interval="1d", progress=False)
    mind = build_mind(config) if (config.get("backtest") or {}).get("use_professional_mind", True) else None

    train_frames, test_frames = frames, None
    train_vix, test_vix = vix, None
    if args.split and frames:
        sample = next(iter(frames.values()))
        if not isinstance(sample.index, pd.DatetimeIndex):
            sample.index = pd.to_datetime(sample.index)
        end = sample.index.max()
        split = end - pd.DateOffset(years=2)
        train_start = end - pd.DateOffset(years=5)
        train_frames = slice_frames(frames, start=train_start, end=split)
        test_frames = slice_frames(frames, start=split, end=end)
        if vix is not None and not vix.empty:
            if not isinstance(vix.index, pd.DatetimeIndex):
                vix.index = pd.to_datetime(vix.index)
            train_vix = vix.loc[(vix.index >= train_start) & (vix.index <= split)]
            test_vix = vix.loc[vix.index >= split]

    risk_grid = parse_float_list(args.risk_grid)
    sym_grid = parse_float_list(args.symbol_pct_grid)
    r_grid = parse_float_list(args.target_r_grid)

    rows = []
    for risk_pct, sym_pct, target_r in itertools.product(risk_grid, sym_grid, r_grid):
        scoped = json.loads(json.dumps(config))
        scoped.setdefault("risk", {})["max_risk_percent"] = risk_pct
        scoped.setdefault("portfolio", {})["max_symbol_pct"] = sym_pct
        scoped.setdefault("swing_trading", {})["target_r_multiple"] = target_r
        scoped.setdefault("swing_trading", {})["target2_r_multiple"] = target_r * 2

        train = evaluate(scoped, train_frames, args.capital, train_vix, mind)
        row = {
            "risk_pct": risk_pct,
            "max_symbol_pct": sym_pct,
            "target_r": target_r,
            "train": train,
        }
        if test_frames:
            row["test"] = evaluate(scoped, test_frames, args.capital, test_vix, mind)
        rows.append(row)

    rows.sort(key=lambda r: (-r["train"]["return_pct"], -r["train"]["pf"]))

    if args.json:
        print(json.dumps(rows[:args.top], indent=2))
    else:
        print(f"掃描 {len(rows)} 組 | 期間 {args.period} | 資本 ${args.capital:.0f}")
        hdr = (
            f"{'risk%':>5} {'sym%':>4} {'R':>4} | "
            f"{'ret%':>6} {'trd':>4} {'wr%':>5} {'pf':>5} {'dd%':>5} {'t/m':>5}"
        )
        if test_frames:
            hdr += " | test_ret%"
        print(hdr)
        for row in rows[:args.top]:
            t = row["train"]
            line = (
                f"{row['risk_pct']:5.1f} {row['max_symbol_pct']:4.0f} {row['target_r']:4.1f} | "
                f"{t['return_pct']:6.1f} {t['trades']:4d} {t['win_rate']:5.1f} "
                f"{t['pf']:5} {t['max_dd']:5.1f} {t['trades_per_month']:5.2f}"
            )
            if test_frames:
                line += f" | {row['test']['return_pct']:6.1f}"
            print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
