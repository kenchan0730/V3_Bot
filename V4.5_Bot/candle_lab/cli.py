#!/usr/bin/env python3
"""Candle Lab CLI — auto-learn, quiz, report, chart."""

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.candle_patterns import CandlePatterns
from core.config_loader import load_config

from candle_lab.dataset import fetch_daily
from candle_lab.engine import CandleLabEngine
from candle_lab.explainer import format_explanation
from candle_lab.learner import load_stats, record_quiz_result, top_weak_spots
from candle_lab.renderer import render_candle_chart


def _config(path="config.yaml", env="data/.env"):
    return load_config(path, env)


def cmd_learn(args):
    config = _config(args.config, args.env)
    symbols = args.symbols or config.get("watchlist", ["AVAH"])
    engine = CandleLabEngine(config)
    result = engine.auto_learn(symbols, save=True)
    print(engine.report_text(result.get("patterns", load_stats().get("patterns", {}))))
    return 0


def cmd_report(args):
    config = _config(args.config, args.env)
    engine = CandleLabEngine(config)
    print(engine.report_text())
    weak = top_weak_spots()
    if weak:
        print("\nQuiz 弱项 Top3:", ", ".join(f"{n}({c})" for n, c in weak))
    return 0


def cmd_chart(args):
    df = fetch_daily(args.symbol, period=args.period)
    if df is None:
        print(f"无法获取 {args.symbol} 数据")
        return 1
    candle = CandlePatterns.identify_all(df)
    out = args.output or f"data/candle_learning/{args.symbol}_chart.png"
    path = render_candle_chart(
        df, args.symbol, out,
        title=f"{args.symbol} | driver={candle.get('driver')} strength={candle.get('strength')}",
        entry=candle.get("entry"),
        stop=candle.get("stop"),
    )
    if path:
        print(f"已保存: {path}")
        if candle.get("driver"):
            print(format_explanation(candle["driver"]))
    return 0 if path else 1


def cmd_quiz(args):
    config = _config(args.config, args.env)
    symbol = args.symbol or random.choice(config.get("watchlist", ["AVAH"]))
    df = fetch_daily(symbol, period="6mo")
    if df is None or len(df) < 70:
        print(f"{symbol} 数据不足")
        return 1

    index = random.randint(60, len(df) - 15)
    window = df.iloc[: index + 1]
    candle = CandlePatterns.identify_all(window)
    driver = candle.get("driver")
    if not driver:
        print(f"{symbol} bar#{index} 无明确形态，换一题…")
        return cmd_quiz(args)

    options = [driver, "无形态", "十字星", "射击之星"]
    options = list(dict.fromkeys(options))[:4]
    random.shuffle(options)
    print(f"\n=== Candle Quiz | {symbol} bar #{index} ===")
    print(f"信号: {candle.get('signal')} | strength {candle.get('strength')}")
    print("这根 K 线的主要形态是？")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")

    if args.auto:
        answer_idx = options.index(driver) + 1
        print(f"(auto 模式正确答案: {answer_idx}. {driver})")
    else:
        try:
            answer_idx = int(input("你的答案 (1-4): ").strip())
        except (EOFError, ValueError):
            print("已取消")
            return 1

    chosen = options[answer_idx - 1] if 1 <= answer_idx <= len(options) else ""
    correct = chosen == driver
    record_quiz_result(driver, correct)
    if correct:
        print("✅ 正确！")
    else:
        print(f"❌ 正确答案: {driver}")
    print(format_explanation(driver))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Candle Lab — K线学习与统计")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--env", default="data/.env")
    sub = parser.add_subparsers(dest="command", required=True)

    p_learn = sub.add_parser("learn", help="自动拉历史K线并学习形态胜率")
    p_learn.add_argument("--symbols", nargs="+", help="股票列表，默认 watchlist")
    p_learn.set_defaults(func=cmd_learn)

    sub.add_parser("report", help="显示形态胜率报告").set_defaults(func=cmd_report)

    p_chart = sub.add_parser("chart", help="输出 K 线图 PNG")
    p_chart.add_argument("--symbol", required=True)
    p_chart.add_argument("--period", default="6mo")
    p_chart.add_argument("--output", default=None)
    p_chart.set_defaults(func=cmd_chart)

    p_quiz = sub.add_parser("quiz", help="形态识别小测验")
    p_quiz.add_argument("--symbol", default=None)
    p_quiz.add_argument("--auto", action="store_true", help="非交互：自动选正确答案")
    p_quiz.set_defaults(func=cmd_quiz)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
