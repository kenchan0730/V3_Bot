#!/usr/bin/env python3
"""Diagnose whether realised per-trade risk matches config max_risk_percent.

Reports average / median risk %, concentration binding rate, and commission drag.
Uses portfolio-level replay when --portfolio is set.

Usage:
    python scripts/sizing_diagnostic.py --capital 1275 --period 2y
    python scripts/sizing_diagnostic.py --portfolio --period 5y --json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yfinance as yf

from backtest.engine import BacktestEngine
from backtest.portfolio_engine import PortfolioBacktestEngine
from backtest.main import build_mind, watchlist_symbols
from core.config_loader import load_config

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="倉位風險診斷")
    parser.add_argument("--symbols", default="", help="逗號分隔；預設 config watchlist")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--capital", type=float, default=1275.0)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--portfolio", action="store_true", help="組合級回測（共享資金）")
    parser.add_argument("--no-throttles", action="store_true", help="關閉 live 節流對照")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def load_frames(symbols, period):
    frames = {}
    for symbol in symbols:
        df = yf.download(symbol, period=period, interval="1d", progress=False)
        if df is None or df.empty or len(df) < 80:
            print(f"{symbol}: 數據不足，略過")
            continue
        frames[symbol] = df
    return frames


def risk_stats(trades, target_risk_pct):
    risks = [t.get("risk_pct") for t in trades if t.get("risk_pct") is not None]
    if not risks:
        return {}
    below_half = sum(1 for r in risks if r < target_risk_pct * 0.5)
    return {
        "trade_count": len(trades),
        "target_risk_pct": target_risk_pct,
        "avg_risk_pct": round(sum(risks) / len(risks), 3),
        "median_risk_pct": round(sorted(risks)[len(risks) // 2], 3),
        "min_risk_pct": round(min(risks), 3),
        "max_risk_pct": round(max(risks), 3),
        "pct_under_half_target": round(below_half / len(risks) * 100, 1),
        "avg_notional": round(
            sum(t["shares"] * t["entry"] for t in trades) / len(trades), 2
        ),
        "avg_costs": round(sum(t.get("costs", 0) for t in trades) / len(trades), 2),
    }


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or watchlist_symbols(config)
    if not symbols:
        print("未指定標的")
        return 1

    target_risk = float((config.get("risk") or {}).get("max_risk_percent", 2.0))
    frames = load_frames(symbols, args.period)
    if not frames:
        print("無可用數據")
        return 1

    use_mind = (config.get("backtest") or {}).get("use_professional_mind", True)
    mind = build_mind(config) if use_mind else None

    if args.portfolio:
        cfg = dict(config)
        if args.no_throttles:
            cfg.setdefault("backtest", {})["use_live_throttles"] = False
        engine = PortfolioBacktestEngine(
            cfg, initial_capital=args.capital, professional_mind=mind,
        )
        vix = yf.download("^VIX", period=args.period, interval="1d", progress=False)
        result = engine.run_portfolio(frames, vix_df=vix)
        trades = result.trades
        summary = result.summary()
    else:
        monthly_target = float((config.get("trade_pacing") or {}).get("target_trades_per_month", 8))
        pacing_target = max(1.0, monthly_target / max(1, len(frames)))
        engine = BacktestEngine(
            config, initial_capital=args.capital, professional_mind=mind,
            pacing_target=pacing_target,
        )
        trades = []
        for symbol, df in frames.items():
            res = engine.run(symbol, df)
            for t in res.trades:
                entry, stop = t["entry"], t.get("stop")
                if stop is None:
                    risk_pct = None
                else:
                    risk_dollars = (entry - stop) * t["shares"]
                    risk_pct = risk_dollars / args.capital * 100
                trades.append({**t, "risk_pct": round(risk_pct, 3) if risk_pct else None})
        summary = {"per_symbol": True, "symbols": len(frames)}

    stats = risk_stats(trades, target_risk)
    out = {"risk_stats": stats, "backtest_summary": summary}

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"模式: {'組合級' if args.portfolio else '逐標的'} | 期間 {args.period} | 資本 ${args.capital:.0f}")
        print(f"目標單筆風險: {target_risk}%")
        for key, value in stats.items():
            print(f"  {key:<22} {value}")
        if args.portfolio:
            print("節流統計:", summary.get("throttle_stats"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
