"""Tests for V4.5 Desktop market_cache OHLCV fallbacks."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

BOT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = BOT_ROOT / "V4.5_Desktop" / "backend"
sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from services import market_cache as mc  # noqa: E402


def test_fetch_ohlcv_falls_back_when_finnhub_candles_empty(monkeypatch):
    monkeypatch.setenv("FINNHUB_KEY", "test-key")
    sample = [{"time": "2024-01-02", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100.0}]

    with patch.object(mc, "_fetch_ohlcv_finnhub", return_value=[]), patch.object(
        mc, "_fetch_ohlcv_alpaca", return_value=[]
    ), patch.object(mc, "_fetch_ohlcv_yfinance", return_value=sample) as yf_mock:
        rows = mc.fetch_ohlcv("AAPL", period="2y")

    assert rows == sample
    yf_mock.assert_called()


def test_fetch_ohlcv_uses_alpaca_before_yfinance(monkeypatch):
    monkeypatch.setenv("FINNHUB_KEY", "test-key")
    sample = [{"time": "2024-03-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 50.0}]

    with patch.object(mc, "_fetch_ohlcv_finnhub", return_value=[]), patch.object(
        mc, "_fetch_ohlcv_alpaca", return_value=sample
    ) as alpaca_mock, patch.object(mc, "_fetch_ohlcv_yfinance") as yf_mock:
        rows = mc.fetch_ohlcv("MSFT", period="1y")

    assert rows == sample
    alpaca_mock.assert_called()
    yf_mock.assert_not_called()


def test_rows_from_history_normalizes_columns():
    idx = pd.date_range("2024-01-01", periods=2, freq="D")
    hist = pd.DataFrame(
        {
            "Open": [10.0, 10.5],
            "High": [10.2, 10.8],
            "Low": [9.8, 10.1],
            "Close": [10.1, 10.6],
            "Volume": [1000, 1200],
        },
        index=idx,
    )
    rows = mc._rows_from_history(hist)
    assert len(rows) == 2
    assert rows[0]["close"] == 10.1
