"""Multi-source OHLCV and realtime quote fetcher with automatic fallback."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytz
import requests
import yfinance as yf

from core.data_utils import normalize_columns

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def _cfg(config: dict[str, Any] | None, key: str, default):
    return (config or {}).get(key, default)


def fetch_daily_bars(symbol: str, ibkr=None, config: dict[str, Any] | None = None):
    """Return (dataframe, source_name) for daily OHLCV."""
    cfg = config or {}
    sources = _cfg(cfg, "daily_sources", ["ibkr", "yfinance"])
    min_bars = int(_cfg(cfg, "min_bars", 60))
    timeout = int(_cfg(cfg, "fetch_timeout_seconds", 30))

    for source in sources:
        df = None
        if source == "ibkr" and ibkr and ibkr.is_connected():
            try:
                raw = ibkr.get_historical_data(symbol, duration="6 M", bar_size="1 day")
                if raw is not None and len(raw) >= min_bars:
                    df = normalize_columns(raw)
            except Exception as exc:
                logger.warning("%s IBKR daily failed: %s", symbol, exc)

        elif source == "yfinance":
            try:
                kwargs = dict(period="6mo", interval="1d", progress=False)
                try:
                    raw = yf.download(symbol, timeout=timeout, **kwargs)
                except TypeError:
                    raw = yf.download(symbol, **kwargs)
                if raw is not None and not raw.empty and len(raw) >= min_bars:
                    df = normalize_columns(raw)
            except Exception as exc:
                logger.warning("%s yfinance daily failed: %s", symbol, exc)

        if df is not None and len(df) >= min_bars:
            return df, source

    return None, None


def fetch_intraday_bars(symbol: str, ibkr=None, config: dict[str, Any] | None = None):
    """Return (dataframe, source_name) for today's intraday bars."""
    cfg = config or {}
    sources = _cfg(cfg, "intraday_sources", ["ibkr", "alpaca", "yfinance"])
    bar_size = _cfg(cfg, "bar_size", "5 mins")
    fallback_interval = _cfg(cfg, "fallback_interval", "5m")
    min_bars = int(_cfg(cfg, "min_intraday_bars", 12))
    timeout = int(_cfg(cfg, "fetch_timeout_seconds", 20))

    for source in sources:
        df = None
        if source == "ibkr" and ibkr and ibkr.is_connected():
            try:
                raw = ibkr.get_historical_data(symbol, duration="1 D", bar_size=bar_size)
                if raw is not None and len(raw) >= max(3, min_bars // 4):
                    df = normalize_columns(raw)
                    if "date" in df.columns:
                        df = df.set_index("date")
            except Exception as exc:
                logger.warning("%s IBKR intraday failed: %s", symbol, exc)

        elif source == "alpaca":
            df = _alpaca_intraday(symbol, cfg, fallback_interval)

        elif source == "yfinance":
            df = _yf_intraday(symbol, fallback_interval, timeout)

        if df is None or df.empty:
            continue

        df = _normalize_intraday_index(df)
        today = datetime.now(ET).date()
        df = df[df.index.date == today]
        if len(df) >= max(3, min_bars // 4):
            return df, source

    return None, None


def fetch_realtime_quote(symbol: str, ibkr=None, config: dict[str, Any] | None = None):
    """Return dict: price, change_pct, timestamp, source, age_seconds."""
    cfg = config or {}
    sources = _cfg(cfg, "quote_sources", ["ibkr", "finnhub", "yfinance", "alpaca"])
    finnhub_key = _cfg(cfg, "finnhub_key", "")

    for source in sources:
        quote = None
        if source == "ibkr" and ibkr and ibkr.is_connected():
            quote = _ibkr_quote(symbol, ibkr)
        elif source == "finnhub" and finnhub_key:
            quote = _finnhub_quote(symbol, finnhub_key)
        elif source == "yfinance":
            quote = _yf_quote(symbol)
        elif source == "alpaca":
            quote = _alpaca_quote(symbol, cfg)

        if quote and quote.get("price"):
            ts = quote.get("timestamp")
            age = None
            if ts:
                age = max(0.0, (datetime.now(ET) - ts).total_seconds())
            quote["age_seconds"] = age
            quote["source"] = source
            return quote

    return {
        "price": None,
        "change_pct": None,
        "timestamp": None,
        "source": None,
        "age_seconds": None,
    }


def assess_quote_freshness(quote: dict[str, Any], max_age_seconds: int) -> dict[str, Any]:
    """Classify quote staleness for logging / optional gates."""
    age = quote.get("age_seconds")
    source = quote.get("source")
    if quote.get("price") is None:
        return {"fresh": False, "stale": True, "reason": "no quote", "source": source}
    if age is None:
        return {"fresh": True, "stale": False, "reason": "unknown age", "source": source}
    if age <= max_age_seconds:
        return {
            "fresh": True,
            "stale": False,
            "reason": f"{int(age)}s old",
            "source": source,
        }
    return {
        "fresh": False,
        "stale": True,
        "reason": f"quote {int(age)}s old (max {max_age_seconds}s)",
        "source": source,
    }


def _normalize_intraday_index(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize(ET, ambiguous="NaT", nonexistent="NaT")
    else:
        df.index = df.index.tz_convert(ET)
    return df.sort_index()


def _yf_intraday(symbol: str, interval: str, timeout: int):
    try:
        kwargs = dict(period="1d", interval=interval, progress=False, prepost=False)
        try:
            raw = yf.download(symbol, timeout=timeout, **kwargs)
        except TypeError:
            raw = yf.download(symbol, **kwargs)
        if raw is None or raw.empty:
            return None
        return normalize_columns(raw)
    except Exception as exc:
        logger.debug("%s yfinance intraday failed: %s", symbol, exc)
        return None


def _yf_quote(symbol: str):
    try:
        ticker = yf.Ticker(symbol.upper())
        info = ticker.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
        if price is None and hasattr(info, "get"):
            price = info.get("lastPrice") or info.get("regularMarketPrice")
        if price is None:
            hist = ticker.history(period="1d", interval="1m")
            if hist is not None and not hist.empty:
                price = float(hist["Close"].iloc[-1])
        if price is None:
            return None
        change_pct = getattr(info, "regular_market_change_percent", None)
        return {
            "price": float(price),
            "change_pct": float(change_pct) if change_pct is not None else None,
            "timestamp": datetime.now(ET),
        }
    except Exception as exc:
        logger.debug("%s yfinance quote failed: %s", symbol, exc)
        return None


def _finnhub_quote(symbol: str, api_key: str):
    try:
        import finnhub

        client = finnhub.Client(api_key=api_key)
        q = client.quote(symbol.upper())
        if not q or q.get("c") in (None, 0):
            return None
        ts = q.get("t")
        timestamp = datetime.fromtimestamp(int(ts), tz=ET) if ts else datetime.now(ET)
        return {
            "price": float(q["c"]),
            "change_pct": float(q.get("dp") or 0),
            "timestamp": timestamp,
        }
    except Exception as exc:
        logger.debug("%s finnhub quote failed: %s", symbol, exc)
        return None


def _ibkr_quote(symbol: str, ibkr):
    try:
        raw = ibkr.get_historical_data(symbol, duration="1 D", bar_size="1 min")
        if raw is None or len(raw) == 0:
            return None
        df = normalize_columns(raw)
        price = float(df["close"].iloc[-1])
        ts_val = df.index[-1] if isinstance(df.index, pd.DatetimeIndex) else None
        if ts_val is not None:
            ts = pd.Timestamp(ts_val)
            if ts.tzinfo is None:
                ts = ts.tz_localize(ET)
            else:
                ts = ts.tz_convert(ET)
            timestamp = ts.to_pydatetime()
        else:
            timestamp = datetime.now(ET)
        return {"price": price, "change_pct": None, "timestamp": timestamp}
    except Exception as exc:
        logger.debug("%s ibkr quote failed: %s", symbol, exc)
        return None


def _alpaca_headers(cfg: dict[str, Any]) -> dict[str, str] | None:
    alpaca = cfg.get("alpaca") or {}
    key = alpaca.get("api_key") or cfg.get("alpaca_api_key") or ""
    secret = alpaca.get("api_secret") or cfg.get("alpaca_api_secret") or ""
    if not key or not secret:
        return None
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }


def _alpaca_intraday(symbol: str, cfg: dict[str, Any], interval: str):
    headers = _alpaca_headers(cfg)
    if not headers:
        return None
    alpaca = cfg.get("alpaca") or {}
    data_url = alpaca.get("data_url", "https://data.alpaca.markets").rstrip("/")
    tf = "5Min" if interval in ("5m", "5 mins", "5 mins") else "1Min"
    start = datetime.now(ET).replace(hour=9, minute=30, second=0, microsecond=0)
    params = {
        "timeframe": tf,
        "start": start.isoformat(),
        "limit": 500,
        "adjustment": "raw",
    }
    try:
        resp = requests.get(
            f"{data_url}/v2/stocks/{symbol.upper()}/bars",
            headers=headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        bars = (resp.json() or {}).get("bars") or []
        if not bars:
            return None
        rows = []
        for bar in bars:
            rows.append(
                {
                    "open": bar["o"],
                    "high": bar["h"],
                    "low": bar["l"],
                    "close": bar["c"],
                    "volume": bar["v"],
                    "date": bar["t"],
                }
            )
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_convert(ET)
        return df.set_index("date")
    except Exception as exc:
        logger.debug("%s alpaca intraday failed: %s", symbol, exc)
        return None


def _alpaca_quote(symbol: str, cfg: dict[str, Any]):
    headers = _alpaca_headers(cfg)
    if not headers:
        return None
    alpaca = cfg.get("alpaca") or {}
    data_url = alpaca.get("data_url", "https://data.alpaca.markets").rstrip("/")
    try:
        resp = requests.get(
            f"{data_url}/v2/stocks/{symbol.upper()}/trades/latest",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        trade = (resp.json() or {}).get("trade") or {}
        price = trade.get("p")
        if price is None:
            return None
        ts_raw = trade.get("t")
        timestamp = (
            pd.to_datetime(ts_raw).tz_convert(ET).to_pydatetime()
            if ts_raw
            else datetime.now(ET)
        )
        return {"price": float(price), "change_pct": None, "timestamp": timestamp}
    except Exception as exc:
        logger.debug("%s alpaca quote failed: %s", symbol, exc)
        return None
