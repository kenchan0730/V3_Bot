"""Tests for candle_lab auto-learn and bot bridge."""

import json

import pytest

from candle_lab.bridge import apply_learned_adjustment, reliability_multiplier
from candle_lab.engine import CandleLabEngine
from candle_lab.explainer import explain, format_explanation
from candle_lab.learner import load_stats, record_quiz_result, save_stats, top_weak_spots
from candle_lab.renderer import render_candle_chart
from core.candle_patterns import CandlePatterns
from core.trading_signals import TradingSignals
from tests.helpers import make_ohlcv


@pytest.fixture
def trending_df():
    closes = [10 + i * 0.08 for i in range(120)]
    volumes = [1_000_000] * 120
    for i in range(70, 120, 10):
        volumes[i] = 2_500_000
    df = make_ohlcv(closes, volumes=volumes)
    col = {n: df.columns.get_loc(n) for n in ("open", "high", "low", "close")}
    for i in range(70, 120, 10):
        c = float(df.iloc[i, col["close"]])
        df.iloc[i, col["open"]] = c - 0.01
        df.iloc[i, col["high"]] = c
        df.iloc[i, col["low"]] = c - 2.0
    return df


def test_engine_scans_patterns_on_synthetic(trending_df):
    engine = CandleLabEngine({"candle": {"learn_forward_bars": 5, "learn_warmup_bars": 60}})
    aggregate = __import__("collections").defaultdict(
        lambda: {"wins": 0, "total": 0, "sum_return_pct": 0.0}
    )
    per_symbol = __import__("collections").defaultdict(
        lambda: __import__("collections").defaultdict(
            lambda: {"wins": 0, "total": 0, "sum_return_pct": 0.0}
        )
    )
    engine._scan_symbol(trending_df, "TEST", aggregate, per_symbol)
    patterns = engine._finalize_stats(aggregate, per_symbol)
    assert patterns
    assert any(data["total"] > 0 for data in patterns.values())


def test_bridge_blocks_weak_win_rate():
    stats = {
        "patterns": {
            "鎚頭": {
                "wins": 2, "total": 10, "win_rate": 0.2,
                "by_symbol": {"AVAH": {"wins": 1, "total": 5, "win_rate": 0.2}},
            }
        }
    }
    mult, reason = reliability_multiplier(
        "AVAH", "鎚頭",
        {"use_learned_stats": True, "min_learned_samples": 5, "min_learned_win_rate": 0.4},
        stats,
    )
    assert mult == 0.0
    assert reason is not None


def test_bridge_boosts_strong_win_rate():
    stats = {
        "patterns": {
            "晨星": {
                "wins": 7, "total": 10, "win_rate": 0.7,
                "by_symbol": {},
            }
        }
    }
    mult, _ = reliability_multiplier(
        "AVAH", "晨星",
        {"use_learned_stats": True, "min_learned_samples": 8, "min_learned_win_rate": 0.4},
        stats,
    )
    assert mult == 1.1


def test_apply_learned_adjustment_neutralizes_weak_pattern():
    candle = {"driver": "鎚頭", "signal": "bullish", "strength": 0.8, "entry": 10.0, "stop": 9.0}
    stats = {
        "patterns": {
            "鎚頭": {"wins": 1, "total": 10, "win_rate": 0.1, "by_symbol": {}},
        }
    }
    cfg = {"use_learned_stats": True, "min_learned_samples": 5, "min_learned_win_rate": 0.4}
    out = apply_learned_adjustment(candle, "AVAH", cfg, stats)
    assert out["signal"] == "neutral"
    assert out.get("learned_blocked") is True


def test_trading_signals_uses_learned_stats(tmp_path, monkeypatch, trending_df):
    stats_path = tmp_path / "auto_stats.json"
    save_stats(
        {
            "鎚頭": {
                "wins": 1, "total": 10, "win_rate": 0.1,
                "avg_return_pct": -1.0, "by_symbol": {},
            }
        },
        path=stats_path,
    )
    monkeypatch.setattr("candle_lab.bridge.load_stats", lambda: json.loads(stats_path.read_text()))

    price = float(trending_df.iloc[-1]["close"])
    ma20 = float(trending_df["close"].rolling(20).mean().iloc[-1])
    ma50 = float(trending_df["close"].rolling(50).mean().iloc[-1])

    # Force hammer on last bar
    i = len(trending_df) - 1
    col = {n: trending_df.columns.get_loc(n) for n in ("open", "high", "low", "close")}
    c = float(trending_df.iloc[i, col["close"]])
    trending_df.iloc[i, col["open"]] = c - 0.01
    trending_df.iloc[i, col["high"]] = c
    trending_df.iloc[i, col["low"]] = c - 2.0

    candle_cfg = {"use_learned_stats": True, "min_learned_samples": 5, "min_learned_win_rate": 0.4}
    signal = TradingSignals.get_combined_signal(
        trending_df, price, 18.0, 1.0, 2.0, ma20, ma50,
        zscore_min=0.5, symbol="AVAH", candle_config=candle_cfg,
    )
    # Weak learned hammer should prevent STRONG_BUY even if other edges pass
    if CandlePatterns.identify_all(trending_df).get("driver") == "鎚頭":
        assert signal["action"] != "STRONG_BUY" or signal.get("learned_candle", {}).get("blocked")


def test_explainer_has_hammer():
    info = explain("鎚頭")
    assert "锤头" in info["definition"] or "鎚頭" in info["name"]
    text = format_explanation("鎚頭")
    assert "鎚頭" in text


def test_quiz_progress(tmp_path, monkeypatch):
    progress_path = tmp_path / "progress.json"
    monkeypatch.setattr("candle_lab.learner.PROGRESS_FILE", progress_path)
    record_quiz_result("鎚頭", False)
    record_quiz_result("鎚頭", False)
    record_quiz_result("晨星", True)
    weak = top_weak_spots(2)
    assert weak[0][0] == "鎚頭"


def test_renderer_smoke(trending_df, tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "chart.png"
    path = render_candle_chart(trending_df, "TEST", out, entry=12.0, stop=10.0)
    assert path is not None
    assert out.exists()
