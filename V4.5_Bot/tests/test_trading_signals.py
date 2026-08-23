import pandas as pd
import pytest

from core.trading_signals import TradingSignals


def _row(open_, high, low, close, volume=1000):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


def _make_df(closes, volumes=None):
    volumes = volumes or [1000] * len(closes)
    rows = []
    for i, close in enumerate(closes):
        rows.append(_row(close - 0.2, close + 0.5, close - 0.5, close, volumes[i]))
    return pd.DataFrame(rows)


def with_hammer(df):
    """Force the final bar into a hammer so candle strength clears +0.4.

    Requires a long lower wick, a tiny body and effectively no upper wick.
    """
    df = df.copy()
    close = float(df["close"].iloc[-1])
    df.iloc[-1, df.columns.get_loc("open")] = close - 0.01
    df.iloc[-1, df.columns.get_loc("high")] = close
    df.iloc[-1, df.columns.get_loc("low")] = close - 2.0
    return df


def with_bearish_engulfing(df):
    df = df.copy()
    df.iloc[-2, df.columns.get_loc("open")] = 10.0
    df.iloc[-2, df.columns.get_loc("close")] = 10.6
    df.iloc[-2, df.columns.get_loc("high")] = 10.7
    df.iloc[-2, df.columns.get_loc("low")] = 9.9
    df.iloc[-1, df.columns.get_loc("open")] = 10.8
    df.iloc[-1, df.columns.get_loc("close")] = 9.8
    df.iloc[-1, df.columns.get_loc("high")] = 10.9
    df.iloc[-1, df.columns.get_loc("low")] = 9.7
    return df


def levels(df):
    price = float(df["close"].iloc[-1])
    ma20 = float(df["close"].rolling(20).mean().iloc[-1])
    ma50 = float(df["close"].rolling(50).mean().iloc[-1])
    return price, ma20, ma50


# ----- HOLD paths -----

def test_hold_when_z_score_below_minimum():
    df = _make_df([10 + i * 0.05 for i in range(70)])
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 20.0, 0.1, 1.6, ma20, ma50, zscore_min=0.5)
    assert signal["action"] == "HOLD"
    assert "無強力信號" in signal["reason"]


def test_hold_when_vix_too_high():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 40.0, 1.0, 1.6, ma20, ma50)
    assert signal["action"] == "HOLD"


def test_hold_when_structure_broken():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, _, _ = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 1.0, 1.6, price + 5, price + 10)
    assert signal["action"] == "HOLD"


def test_hold_when_volume_ratio_neutral():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 1.0, 1.0, ma20, ma50)
    assert signal["action"] == "HOLD"


# ----- STRONG_BUY -----

def test_strong_buy_full_setup():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 1.0, 1.6, ma20, ma50, zscore_min=0.5)
    assert signal["action"] == "STRONG_BUY"
    assert signal["stop"] < signal["entry"] < signal["target1"] < signal["target2"]


def test_confidence_is_numeric_for_risk_layer():
    """Regression: a string here raised ValueError in ProfessionalMind."""
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 1.0, 1.6, ma20, ma50)
    assert isinstance(signal["confidence"], float)
    assert 0.0 < signal["confidence"] <= 1.0
    assert float(signal["confidence"]) == signal["confidence"]
    assert signal["confidence_label"] in ("HIGH", "MEDIUM", "LOW")


def test_confluence_score_rewards_aligned_edges():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    calm_strong = TradingSignals.get_combined_signal(df, price, 15.0, 1.0, 2.5, ma20, ma50)
    marginal = TradingSignals.get_combined_signal(df, price, 24.0, 0.55, 1.6, ma20, ma50)
    assert calm_strong["action"] == marginal["action"] == "STRONG_BUY"
    assert calm_strong["confluence_score"] > marginal["confluence_score"]
    assert calm_strong["confidence"] > marginal["confidence"]


def test_confluence_score_capped_and_graded():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 15.0, 1.0, 2.5, ma20, ma50)
    assert 5 <= signal["confluence_score"] <= 10
    assert set(signal["strong_edges"]).issubset(set(signal["edges"]))


def test_hold_reports_missing_edges():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 40.0, 1.0, 1.6, ma20, ma50)
    assert signal["action"] == "HOLD"
    assert "volatility" in signal["missing_edges"]
    assert signal["confluence_score"] < 5


def test_strong_buy_risk_reward_ratios():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 1.0, 1.6, ma20, ma50)
    risk = signal["entry"] - signal["stop"]
    assert signal["target1"] == pytest.approx(signal["entry"] + risk * 1.5, abs=0.02)
    assert signal["target2"] == pytest.approx(signal["entry"] + risk * 3.0, abs=0.02)


def test_zscore_min_gates_entry():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    permissive = TradingSignals.get_combined_signal(df, price, 18.0, 0.6, 1.6, ma20, ma50, zscore_min=0.5)
    strict = TradingSignals.get_combined_signal(df, price, 18.0, 0.6, 1.6, ma20, ma50, zscore_min=0.8)
    assert permissive["action"] == "STRONG_BUY"
    assert strict["action"] == "HOLD"


def test_z_score_above_band_is_hold():
    df = with_hammer(_make_df([10 + i * 0.1 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 2.5, 1.6, ma20, ma50)
    assert signal["action"] == "HOLD"


# ----- STRONG_SELL -----

def test_strong_sell_on_bearish_pattern():
    df = with_bearish_engulfing(_make_df([10 + i * 0.02 for i in range(70)]))
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 1.0, 1.6, ma20, ma50)
    assert signal["action"] == "STRONG_SELL"
    assert "K線形態" in signal["reason"]


def test_strong_sell_ignores_technical_gates():
    df = with_bearish_engulfing(_make_df([10 + i * 0.02 for i in range(70)]))
    price, _, _ = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 40.0, 0.0, 1.0, price + 5, price + 9)
    assert signal["action"] == "STRONG_SELL"


# ----- normalization -----

def test_normalizes_uppercase_columns():
    raw = _make_df([10 + i * 0.05 for i in range(70)]).rename(columns=str.capitalize)
    price = float(raw["Close"].iloc[-1])
    ma20 = float(raw["Close"].rolling(20).mean().iloc[-1])
    ma50 = float(raw["Close"].rolling(50).mean().iloc[-1])
    signal = TradingSignals.get_combined_signal(raw, price, 20.0, 0.2, 1.6, ma20, ma50)
    assert "action" in signal


def test_falls_back_to_price_when_candle_lacks_levels():
    df = _make_df([10 + i * 0.1 for i in range(70)])
    df = with_hammer(df)
    price, ma20, ma50 = levels(df)
    signal = TradingSignals.get_combined_signal(df, price, 18.0, 1.0, 0.5, ma20, ma50)
    assert signal["action"] in ("STRONG_BUY", "HOLD")
