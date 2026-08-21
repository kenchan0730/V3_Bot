"""Watchlist correlation analysis used to avoid clustered risk."""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def weekly_returns(close_series):
    """Resample a daily close series into weekly percentage returns."""
    if close_series is None or len(close_series) < 2:
        return pd.Series(dtype="float64")
    series = close_series.copy()
    if not isinstance(series.index, pd.DatetimeIndex):
        try:
            series.index = pd.to_datetime(series.index)
        except Exception:
            return series.pct_change().dropna()
    return series.resample("W").last().pct_change().dropna()


def correlation_matrix(closes_by_symbol, use_weekly=True, min_observations=8):
    """Build a correlation matrix from {symbol: close_series}."""
    frames = {}
    for symbol, closes in (closes_by_symbol or {}).items():
        returns = weekly_returns(closes) if use_weekly else closes.pct_change().dropna()
        if len(returns) >= min_observations:
            frames[symbol] = returns
    if len(frames) < 2:
        return pd.DataFrame()
    return pd.DataFrame(frames).corr()


def clustered_pairs(matrix, threshold=0.8):
    """Return [(symbol_a, symbol_b, corr)] above the threshold."""
    pairs = []
    if matrix is None or matrix.empty:
        return pairs
    symbols = list(matrix.columns)
    for i, first in enumerate(symbols):
        for second in symbols[i + 1:]:
            value = matrix.loc[first, second]
            if value is not None and value == value and abs(value) >= threshold:
                pairs.append((first, second, round(float(value), 3)))
    return sorted(pairs, key=lambda item: -abs(item[2]))
