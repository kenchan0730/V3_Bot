"""Robust market quotes and ETF snapshots for V4.5 Desktop."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import requests
import yfinance as yf

from core.data_utils import normalize_columns
from core.yf_throttle import silence_yfinance_logs, throttled

silence_yfinance_logs()
logger = logging.getLogger(__name__)

SECTOR_LEAD_STOCKS = {
    "XLK": ("Technology", "AAPL"),
    "XLE": ("Energy", "XOM"),
    "XLV": ("Healthcare", "UNH"),
    "XLF": ("Financials", "JPM"),
    "XLI": ("Industrials", "CAT"),
    "XLY": ("Consumer Cyclical", "AMZN"),
    "XLP": ("Consumer Defensive", "WMT"),
    "XLC": ("Communication Services", "GOOGL"),
    "SMH": ("Semiconductor", "NVDA"),
    "XLB": ("Materials", "LIN"),
    "XLRE": ("Real Estate", "PLD"),
}

_finnhub_client: Any = None
FINNHUB_GAP = 1.05


class TTLCache:
    def __init__(self, ttl_seconds: float = 60.0):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        item = self._store.get(key)
        if not item:
            return None
        ts, value = item
        if time.time() - ts > self.ttl:
            return None
        return value

    def set(self, key: str, value: Any) -> Any:
        self._store[key] = (time.time(), value)
        return value

    def get_or_set(self, key: str, factory) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        return self.set(key, factory())


def _empty_quote(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "price": 0.0,
        "change_pct": 0.0,
        "direction": "flat",
    }


def _finnhub_key() -> str:
    return os.environ.get("FINNHUB_API_KEY") or os.environ.get("FINNHUB_KEY") or ""


def _alpaca_headers() -> Optional[dict[str, str]]:
    key = (
        os.environ.get("ALPACA_API_KEY")
        or os.environ.get("APCA_API_KEY_ID")
        or ""
    )
    secret = (
        os.environ.get("ALPACA_API_SECRET")
        or os.environ.get("ALPACA_SECRET_KEY")
        or os.environ.get("APCA_API_SECRET_KEY")
        or ""
    )
    if not key or not secret:
        return None
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }


def _period_days(period: str) -> int:
    return {"6mo": 183, "1y": 365, "2y": 730}.get(period, 730)


def _get_finnhub():
    global _finnhub_client
    if _finnhub_client is not None:
        return _finnhub_client
    key = _finnhub_key()
    if not key:
        return None
    try:
        import finnhub

        _finnhub_client = finnhub.Client(api_key=key)
    except Exception as exc:
        logger.debug("finnhub init: %s", exc)
        return None
    return _finnhub_client


def _quote_finnhub(symbol: str) -> Optional[dict[str, Any]]:
    client = _get_finnhub()
    if not client:
        return None
    try:
        q = client.quote(symbol.upper())
        price = float(q.get("c") or 0)
        if price <= 0:
            return None
        chg_pct = float(q.get("dp") or 0)
        return {
            "symbol": symbol.upper(),
            "price": round(price, 2),
            "change_pct": round(chg_pct, 2),
            "direction": "up" if chg_pct >= 0 else "down",
        }
    except Exception as exc:
        logger.debug("finnhub quote %s: %s", symbol, exc)
        return None


def _yf_symbol(symbol: str) -> str:
    sym = symbol.upper()
    return "BRK-B" if sym == "BRK.B" else sym


def _ticker_history(symbol: str, period: str = "5d"):
    sym = _yf_symbol(symbol)

    def _load():
        return yf.Ticker(sym).history(period=period, interval="1d", auto_adjust=True)

    try:
        return throttled(_load)
    except Exception as exc:
        logger.debug("yfinance history %s: %s", symbol, exc)
        return None


def _quote_yfinance_history(symbol: str) -> Optional[dict[str, Any]]:
    hist = _ticker_history(symbol, "5d")
    if hist is None or hist.empty:
        hist = _ticker_history(symbol, "1mo")
    if hist is None or hist.empty:
        return None
    df = normalize_columns(hist)
    closes = df["close"]
    if hasattr(closes, "columns"):
        closes = closes.iloc[:, 0]
    last = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) > 1 else last
    chg = ((last - prev) / prev * 100) if prev else 0.0
    return {
        "symbol": symbol.upper(),
        "price": round(last, 2),
        "change_pct": round(chg, 2),
        "direction": "up" if chg >= 0 else "down",
    }


def quote_one(symbol: str) -> dict[str, Any]:
    sym = symbol.upper()
    q = _quote_finnhub(sym)
    if q:
        return q
    return _quote_yfinance_history(sym) or _empty_quote(sym)


def batch_quotes(symbols: list[str], max_workers: int = 1) -> dict[str, dict[str, Any]]:
    unique = list(dict.fromkeys(s.upper() for s in symbols if s))
    if not unique:
        return {}
    out: dict[str, dict[str, Any]] = {}
    has_fh = bool(_finnhub_key())
    for sym in unique:
        out[sym] = quote_one(sym)
        if has_fh and out[sym]["price"] <= 0:
            time.sleep(FINNHUB_GAP)
    return out


def _rows_from_history(hist) -> list[dict[str, Any]]:
    if hist is None or hist.empty:
        return []
    df = normalize_columns(hist)
    ohlcv: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        ts = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        ohlcv.append({
            "time": ts,
            "open": round(float(row["open"]), 4),
            "high": round(float(row["high"]), 4),
            "low": round(float(row["low"]), 4),
            "close": round(float(row["close"]), 4),
            "volume": float(row.get("volume", 0) or 0),
        })
    return ohlcv


def _fetch_ohlcv_finnhub(symbol: str, period: str = "2y") -> list[dict[str, Any]]:
    client = _get_finnhub()
    if not client:
        return []
    days = _period_days(period)
    end = int(datetime.now().timestamp())
    start = int((datetime.now() - timedelta(days=days)).timestamp())
    try:
        data = client.stock_candles(symbol.upper(), "D", start, end)
        if not data or data.get("s") != "ok":
            return []
        ohlcv = []
        for i, ts in enumerate(data.get("t") or []):
            ohlcv.append({
                "time": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
                "open": round(float(data["o"][i]), 4),
                "high": round(float(data["h"][i]), 4),
                "low": round(float(data["l"][i]), 4),
                "close": round(float(data["c"][i]), 4),
                "volume": float(data["v"][i]),
            })
        return ohlcv
    except Exception as exc:
        logger.debug("finnhub candles %s (%s): %s", symbol, period, exc)
        return []


def _fetch_ohlcv_alpaca(symbol: str, period: str = "2y") -> list[dict[str, Any]]:
    headers = _alpaca_headers()
    if not headers:
        return []
    days = _period_days(period)
    data_url = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets").rstrip("/")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "timeframe": "1Day",
        "start": start,
        "limit": 10000,
        "adjustment": "split",
    }
    try:
        resp = requests.get(
            f"{data_url}/v2/stocks/{symbol.upper()}/bars",
            headers=headers,
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        bars = (resp.json() or {}).get("bars") or []
        if not bars:
            return []
        ohlcv: list[dict[str, Any]] = []
        for bar in bars:
            ts = str(bar.get("t") or "")[:10]
            if not ts:
                continue
            ohlcv.append({
                "time": ts,
                "open": round(float(bar["o"]), 4),
                "high": round(float(bar["h"]), 4),
                "low": round(float(bar["l"]), 4),
                "close": round(float(bar["c"]), 4),
                "volume": float(bar.get("v") or 0),
            })
        return ohlcv
    except Exception as exc:
        logger.debug("alpaca candles %s (%s): %s", symbol, period, exc)
        return []


def _fetch_ohlcv_yfinance(symbol: str, period: str = "2y") -> list[dict[str, Any]]:
    yf_sym = _yf_symbol(symbol)

    def _load():
        return yf.Ticker(yf_sym).history(period=period, interval="1d", auto_adjust=True)

    try:
        hist = throttled(_load)
        if (hist is None or hist.empty) and period != "6mo":
            hist = throttled(lambda: yf.Ticker(yf_sym).history(period="6mo", interval="1d", auto_adjust=True))
        return _rows_from_history(hist)
    except Exception as exc:
        logger.warning("yfinance ohlcv %s (%s) failed: %s", symbol, period, exc)
        return []


def fetch_ohlcv(symbol: str, period: str = "2y") -> list[dict[str, Any]]:
    sym = symbol.upper()
    periods = [period]
    for fallback in ("6mo", "1y", "2y"):
        if fallback not in periods:
            periods.append(fallback)

    if _finnhub_key():
        for p in periods:
            rows = _fetch_ohlcv_finnhub(sym, p)
            if rows:
                return rows

    for p in periods:
        rows = _fetch_ohlcv_alpaca(sym, p)
        if rows:
            return rows

    for p in periods:
        rows = _fetch_ohlcv_yfinance(sym, p)
        if rows:
            return rows
    return []


def etf_snapshot(symbol: str, name: str) -> Optional[dict[str, Any]]:
    q = quote_one(symbol)
    if q["price"] <= 0:
        return None
    spark = [q["price"]]
    ohlcv = fetch_ohlcv(symbol, period="6mo")
    if ohlcv:
        spark = [float(bar["close"]) for bar in ohlcv[-20:]] or spark
    else:
        hist = _ticker_history(symbol, "5d")
        if hist is not None and not hist.empty:
            df = normalize_columns(hist)
            closes = df["close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            spark = [float(x) for x in closes.tail(20).tolist()] or spark
    return {
        "symbol": symbol,
        "name": name,
        "price": q["price"],
        "change_pct": q["change_pct"],
        "sparkline": spark,
    }


def batch_etf_snapshots(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym, name in pairs:
        snap = etf_snapshot(sym, name)
        if snap:
            rows.append(snap)
    return rows


def sector_rows() -> list[dict[str, Any]]:
    """Sector performance from live quotes (Finnhub-first, no bulk yf.download)."""
    symbols = list(SECTOR_LEAD_STOCKS.keys()) + [s[1] for s in SECTOR_LEAD_STOCKS.values()]
    quotes = batch_quotes(symbols)
    spy_chg = float((quotes.get("SPY") or _empty_quote("SPY"))["change_pct"])
    rows: list[dict[str, Any]] = []
    for etf, (name, lead) in SECTOR_LEAD_STOCKS.items():
        etf_q = quotes.get(etf) or _empty_quote(etf)
        lead_q = quotes.get(lead) or _empty_quote(lead)
        chg = float(etf_q["change_pct"] or lead_q["change_pct"])
        rows.append({
            "symbol": etf,
            "name": name,
            "change_pct": round(chg, 2),
            "vs_spy": round(chg - spy_chg, 2),
            "lead_stock": lead,
            "lead_price": lead_q["price"],
            "lead_change_pct": lead_q["change_pct"],
        })
    rows.sort(key=lambda x: x["change_pct"], reverse=True)
    return rows[:11]
