"""CLI: python -m backtest --symbols AVAH,QXO --period 2y"""

import argparse
import json
import logging
import sys

import pandas as pd
import yfinance as yf

from backtest.engine import BacktestEngine
from backtest.portfolio_engine import PortfolioBacktestEngine
from core.config_loader import load_config
from core.correlation import clustered_pairs, correlation_matrix
from core.data_utils import normalize_columns
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
    parser.add_argument("--no-retail", action="store_true", help="關閉散戶思維層（僅供對照）")
    parser.add_argument("--no-pacing", action="store_true", help="關閉交易節奏調節（僅供對照）")
    parser.add_argument("--portfolio", action="store_true", help="組合級回測（共享資金池）")
    parser.add_argument("--no-throttles", action="store_true", help="組合回測時關閉 live 節流")
    return parser.parse_args(argv)


def build_mind(config):
    """Backtest uses the live deliberation layer, minus journal side effects."""
    mind_cfg = dict(config.get("professional_mind", {}) or {})
    mind_cfg["log_every_deliberation"] = False
    mind_cfg["journal_file"] = "data/backtest_journal.csv"
    return ProfessionalMind(mind_cfg)


def close_series(df):
    """Close column as a 1-D Series, tolerating yfinance's MultiIndex columns."""
    frame = normalize_columns(df)
    if "close" not in frame.columns:
        return None
    series = frame["close"]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    return series


def watchlist_symbols(config):
    """Flatten the core/satellite watchlist shape into a plain symbol list."""
    wl = config.get("watchlist", [])
    if isinstance(wl, dict):
        return list(dict.fromkeys((wl.get("core") or []) + (wl.get("satellite") or [])))
    return list(wl)


def main(argv=None):
    args = parse_args(argv)
    config = load_config(args.config)
    cfg_hold = int((config.get("backtest") or {}).get("max_hold_bars", 0) or 0)
    if cfg_hold:
        args.max_hold_bars = cfg_hold
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or watchlist_symbols(config)
    if not symbols:
        print("未指定標的")
        return 1

    if args.no_costs:
        config.setdefault("backtest", {})["apply_costs"] = False
    if args.no_retail:
        config.setdefault("backtest", {})["use_retail_mind"] = False
    if args.no_pacing:
        config.setdefault("backtest", {})["use_pacing"] = False

    if args.no_pacing:
        config.setdefault("backtest", {})["use_pacing"] = False
    if args.no_throttles:
        config.setdefault("backtest", {})["use_live_throttles"] = False

    use_mind = config.get("backtest", {}).get("use_professional_mind", True)
    mind = None if args.no_mind or not use_mind else build_mind(config)

    if args.portfolio:
        engine = PortfolioBacktestEngine(
            config, initial_capital=args.capital, max_hold_bars=args.max_hold_bars,
            professional_mind=mind,
        )
        frames, closes = {}, {}
        for symbol in symbols:
            df = yf.download(symbol, period=args.period, interval="1d", progress=False)
            if df is None or df.empty or len(df) < 80:
                print(f"{symbol}: 數據不足，略過")
                continue
            frames[symbol] = df
            closes[symbol] = close_series(df)
        if not frames:
            print("無可用數據")
            return 1
        vix = yf.download("^VIX", period=args.period, interval="1d", progress=False)
        result = engine.run_portfolio(frames, vix_df=vix)
        summaries = {"PORTFOLIO": result.summary()}
        if not args.json:
            print(
                f"模式: 組合級 | 券商 {engine.broker_profile} | "
                f"成本: {'啟用' if engine.apply_costs else '關閉'} | "
                f"心態層: {'啟用' if mind else '關閉'} | "
                f"散戶層: {'啟用' if engine.use_retail_mind else '關閉'} | "
                f"節流: {'啟用' if engine.use_live_throttles else '關閉'}"
            )
            print("\n=== PORTFOLIO ===")
            for key, value in result.summary().items():
                print(f"  {key:<20} {value}")
            for trade in result.trades[-8:]:
                print(
                    f"    {trade.get('symbol')} {trade.get('entry_date')} "
                    f"{trade['entry']}->{trade['exit']} pnl={trade['pnl']} ({trade['reason']})"
                )
    else:
        # The monthly target is portfolio-wide; a per-symbol replay gets its share.
        monthly_target = float(
            (config.get("trade_pacing", {}) or {}).get("target_trades_per_month", 8)
        )
        pacing_target = max(1.0, monthly_target / max(1, len(symbols)))

        engine = BacktestEngine(
            config, initial_capital=args.capital, max_hold_bars=args.max_hold_bars,
            professional_mind=mind, pacing_target=pacing_target,
        )
        if not args.json:
            print(
                f"成本模型: {'啟用' if engine.apply_costs else '關閉'} | "
                f"心態層審批: {'啟用' if mind else '關閉'} | "
                f"散戶層: {'啟用' if engine.use_retail_mind else '關閉'} | "
                f"節奏調節: {'啟用' if engine.use_pacing else '關閉'} "
                f"(每標的 {pacing_target:.2f} 單/月)"
            )
        summaries, closes = {}, {}

        for symbol in symbols:
            df = yf.download(symbol, period=args.period, interval="1d", progress=False)
            if df is None or df.empty or len(df) < 80:
                print(f"{symbol}: 數據不足，略過")
                continue
            result = engine.run(symbol, df)
            summaries[symbol] = result.summary()
            closes[symbol] = close_series(df)

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
