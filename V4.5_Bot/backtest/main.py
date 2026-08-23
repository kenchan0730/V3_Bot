"""CLI: python -m backtest --symbols AVAH,QXO --period 2y"""

import argparse
import json
import logging
import sys

import yfinance as yf

from backtest.engine import BacktestEngine
from core.config_loader import load_config
from core.correlation import clustered_pairs, correlation_matrix
from core.professional_mind import ProfessionalMind

logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="V4.5 回測")
    parser.add_argument("--symbols", default="", help="逗號分隔；預設使用 config watchlist")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--max-hold-bars", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="以 JSON 輸出")
    parser.add_argument("--no-costs", action="store_true", help="關閉手續費/滑點（僅供對照）")
    parser.add_argument("--no-mind", action="store_true", help="跳過心態層審批（僅供對照）")
    return parser.parse_args(argv)


def build_mind(config):
    """Backtest uses the live deliberation layer, minus journal side effects."""
    mind_cfg = dict(config.get("professional_mind", {}) or {})
    mind_cfg["log_every_deliberation"] = False
    mind_cfg["journal_file"] = "data/backtest_journal.csv"
    return ProfessionalMind(mind_cfg)


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or config.get("watchlist", [])
    if not symbols:
        print("未指定標的")
        return 1

    if args.no_costs:
        config.setdefault("backtest", {})["apply_costs"] = False

    use_mind = config.get("backtest", {}).get("use_professional_mind", True)
    mind = None if args.no_mind or not use_mind else build_mind(config)

    engine = BacktestEngine(
        config, initial_capital=args.capital, max_hold_bars=args.max_hold_bars,
        professional_mind=mind,
    )
    if not args.json:
        print(
            f"成本模型: {'啟用' if engine.apply_costs else '關閉'} | "
            f"心態層審批: {'啟用' if mind else '關閉'}"
        )
    summaries, closes = {}, {}

    for symbol in symbols:
        df = yf.download(symbol, period=args.period, interval="1d", progress=False)
        if df is None or df.empty or len(df) < 80:
            print(f"{symbol}: 數據不足，略過")
            continue
        result = engine.run(symbol, df)
        summaries[symbol] = result.summary()
        closes[symbol] = result and df["Close"] if "Close" in df.columns else None

        if not args.json:
            print(f"\n=== {symbol} ===")
            for key, value in result.summary().items():
                print(f"  {key:<20} {value}")
            for trade in result.trades[-5:]:
                print(f"    {trade['entry_index']}->{trade['exit_index']} "
                      f"{trade['entry']}->{trade['exit']} pnl={trade['pnl']} ({trade['reason']})")

    matrix = correlation_matrix({s: c for s, c in closes.items() if c is not None})
    pairs = clustered_pairs(matrix, config.get("portfolio", {}).get("correlation_threshold", 0.8))

    if args.json:
        print(json.dumps({"summaries": summaries, "clustered_pairs": pairs}, indent=2))
    elif pairs:
        print("\n=== 高相關性配對（建議降低同時持倉）===")
        for first, second, corr in pairs:
            print(f"  {first} / {second}: {corr}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
