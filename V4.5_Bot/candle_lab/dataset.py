"""Fetch OHLCV history for auto-learning (no user-supplied images)."""

import logging

import pandas as pd
import yfinance as yf

from core.data_utils import normalize_columns

logger = logging.getLogger(__name__)


def fetch_daily(symbol, period="6mo", timeout=30):
    """Download daily bars; returns normalized lowercase OHLCV or None."""
    try:
        try:
            raw = yf.download(symbol, period=period, interval="1d", progress=False, timeout=timeout)
        except TypeError:
            raw = yf.download(symbol, period=period, interval="1d", progress=False)
    except Exception as exc:
        logger.warning(f"{symbol} yfinance 下载失败: {exc}")
        return None

    if raw is None or len(raw) == 0:
        return None

    df = normalize_columns(raw)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.reset_index(drop=True)
