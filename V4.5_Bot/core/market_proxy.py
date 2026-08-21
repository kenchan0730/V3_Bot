"""Free macro proxies via yfinance — no Polygon/Tiingo required.

Combines SPY trend, VIX level/term, credit stress (HYG/LQD), and growth tilt
(QQQ/SPY) into a single snapshot for regime detection.
"""

import logging
from functools import lru_cache
from time import time

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE = {}
_CACHE_TTL = 300  # 5 minutes


def _cached(key, loader, ttl=_CACHE_TTL):
    now = time()
    entry = _CACHE.get(key)
    if entry and now - entry["ts"] < ttl:
        return entry["value"]
    value = loader()
    _CACHE[key] = {"ts": now, "value": value}
    return value


def _history(ticker, period="6mo", interval="1d"):
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close_col = "Close" if "Close" in df.columns else "close"
        return df[close_col].dropna()
    except Exception as exc:
        logger.warning(f"market_proxy {ticker} failed: {exc}")
        return None


def _above_ma(series, window):
    if series is None or len(series) < window + 1:
        return None
    ma = series.rolling(window).mean().iloc[-1]
    return float(series.iloc[-1]) > float(ma)


def _return_pct(series, days=20):
    if series is None or len(series) <= days:
        return None
    start = float(series.iloc[-days - 1])
    end = float(series.iloc[-1])
    if start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def fetch_macro_snapshot(ttl=_CACHE_TTL):
    """Return a dict of macro indicators used by RegimeDetector."""

    def load():
        spy = _history("SPY")
        qqq = _history("QQQ")
        vix = _history("^VIX", period="3mo")
        vix3m = _history("^VIX3M", period="3mo")
        hyg = _history("HYG", period="6mo")
        lqd = _history("LQD", period="6mo")

        credit_ratio = None
        credit_trend = None
        if hyg is not None and lqd is not None:
            aligned = pd.concat([hyg, lqd], axis=1, join="inner")
            aligned.columns = ["hyg", "lqd"]
            if len(aligned) >= 2:
                ratio = (aligned["hyg"] / aligned["lqd"]).dropna()
                credit_ratio = float(ratio.iloc[-1]) if len(ratio) else None
                if len(ratio) >= 21:
                    credit_trend = float(ratio.iloc[-1] / ratio.iloc[-21] - 1.0) * 100.0

        vix_level = float(vix.iloc[-1]) if vix is not None and len(vix) else None
        vix3m_level = float(vix3m.iloc[-1]) if vix3m is not None and len(vix3m) else None
        vix_term_spread = None
        if vix_level is not None and vix3m_level is not None:
            vix_term_spread = vix_level - vix3m_level  # positive = backwardation / stress

        qqq_spy = None
        if spy is not None and qqq is not None:
            aligned = pd.concat([qqq, spy], axis=1, join="inner").dropna()
            if len(aligned) >= 2:
                qqq_spy = float(aligned.iloc[-1, 0] / aligned.iloc[-1, 1])

        return {
            "spy_above_ma50": _above_ma(spy, 50),
            "spy_above_ma200": _above_ma(spy, 200),
            "spy_return_20d": _return_pct(spy, 20),
            "vix": vix_level,
            "vix3m": vix3m_level,
            "vix_term_spread": vix_term_spread,
            "credit_ratio": credit_ratio,
            "credit_trend_pct": credit_trend,
            "qqq_spy_ratio": qqq_spy,
            "growth_leading": (
                _return_pct(qqq, 20) is not None
                and _return_pct(spy, 20) is not None
                and _return_pct(qqq, 20) > _return_pct(spy, 20)
            ),
        }

    return _cached("macro_snapshot", load, ttl=ttl)


def clear_cache():
    _CACHE.clear()
