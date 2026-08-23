"""Tests for intraday VWAP / opening-range logic."""

import pandas as pd
import pytest
import pytz

from core.intraday_engine import IntradayEngine

ET = pytz.timezone("America/New_York")


@pytest.fixture
def engine():
    return IntradayEngine({
        "enabled": True,
        "opening_range_minutes": 30,
        "max_distance_from_vwap_pct": 5.0,
        "min_intraday_bars": 6,
        "skip_first_minutes": 0,
        "skip_last_minutes": 0,
    })


def _sample_intraday():
    idx = pd.date_range("2024-06-03 09:35", periods=12, freq="5min", tz=ET)
    prices = [10.0, 10.1, 10.2, 10.15, 10.3, 10.25, 10.4, 10.35, 10.5, 10.45, 10.55, 10.5]
    return pd.DataFrame({
        "open": prices,
        "high": [p + 0.1 for p in prices],
        "low": [p - 0.1 for p in prices],
        "close": prices,
        "volume": [100000] * len(prices),
    }, index=idx)


def test_compute_vwap(engine):
    df = _sample_intraday()
    vwap = engine.compute_vwap(df)
    assert vwap is not None
    assert len(vwap) == len(df)
    assert vwap.iloc[-1] > 0


def test_opening_range(engine):
    df = _sample_intraday()
    orb = engine.opening_range(df)
    assert orb["high"] >= orb["low"]
    assert orb["minutes"] == 30


def test_evaluate_entry_passes_near_vwap(engine, monkeypatch):
    df = _sample_intraday()
    monkeypatch.setattr(engine, "in_trade_window", lambda now=None: (True, "OK"))
    result = engine.evaluate_entry("TEST", "STRONG_BUY", 10.6, df=df)
    assert result["ok"] is True
    assert "entry_price" in result


def test_evaluate_entry_rejects_far_from_vwap(engine, monkeypatch):
    df = _sample_intraday()
    engine.cfg["max_distance_from_vwap_pct"] = 0.01
    monkeypatch.setattr(engine, "in_trade_window", lambda now=None: (True, "OK"))
    result = engine.evaluate_entry("TEST", "STRONG_BUY", 15.0, df=df)
    assert result["ok"] is False


def test_vwap_pullback_uses_percent_not_double_scaled(engine, monkeypatch):
    df = _sample_intraday()
    engine.cfg["vwap_pullback_pct"] = 0.8
    monkeypatch.setattr(engine, "in_trade_window", lambda now=None: (True, "OK"))
    vwap = float(engine.compute_vwap(df).iloc[-1])
    proposed = vwap * 1.05
    result = engine.evaluate_entry("TEST", "STRONG_BUY", proposed, df=df)
    assert result["ok"] is True
    expected_cap = round(vwap * 1.008, 2)
    assert result["entry_price"] == pytest.approx(expected_cap, abs=0.02)
    assert result["entry_price"] > vwap * 1.001
