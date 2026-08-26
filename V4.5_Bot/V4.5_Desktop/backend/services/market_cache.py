"""Robust market quotes and ETF snapshots for V4.5 Desktop."""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

import yfinance as yf

from core.data_utils import normalize_columns

logger = logging.getLogger(__name__)

# Sector ETF -> representative leading stock
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


def _quote_finnhub(symbol: str) -> Optional[dict[str, Any]]:
    key = _finnhub_key()
    if not key:
        return None
    try:
        import finnhub

        q = finnhub.Client(api_key=key).quote(symbol.upper())
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


def _quote_yfinance_history(symbol: str) -> Optional[dict[str, Any]]:
    sym = _yf_symbol(symbol)
    try:
        ticker = yf.Ticker(sym)
        hist = ticker.history(period="5d", interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            hist = ticker.history(period="1mo", interval="1d", auto_adjust=True)
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
    except Exception as exc:
        logger.debug("yfinance history %s: %s", symbol, exc)
        return None


def quote_one(symbol: str) -> dict[str, Any]:
    sym = symbol.upper()
    q = _quote_finnhub(sym) or _quote_yfinance_history(sym)
    return q or _empty_quote(sym)


def batch_quotes(symbols: list[str], max_workers: int = 10) -> dict[str, dict[str, Any]]:
    unique = list(dict.fromkeys(s.upper() for s in symbols if s))
    if not unique:
        return {}
    out: dict[str, dict[str, Any]] = {}
    workers = min(max_workers, max(1, len(unique)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(quote_one, sym): sym for sym in unique}
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                out[sym] = fut.result()
            except Exception as exc:
                logger.debug("batch quote %s: %s", sym, exc)
                out[sym] = _empty_quote(sym)
    for sym in unique:
        out.setdefault(sym, _empty_quote(sym))
    return out


def fetch_ohlcv(symbol: str, period: str = "2y") -> list[dict[str, Any]]:
    sym = symbol.upper()
    yf_sym = _yf_symbol(sym)
    try:
        hist = yf.Ticker(yf_sym).history(period=period, interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return []
        df = normalize_columns(hist)
        ohlcv = []
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
    except Exception as exc:
        logger.warning("ohlcv %s failed: %s", sym, exc)
        return []


def etf_snapshot(symbol: str, name: str) -> Optional[dict[str, Any]]:
    q = quote_one(symbol)
    if q["price"] <= 0:
        return None
    try:
        hist = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=True)
        spark: list[float] = []
        if hist is not None and not hist.empty:
            df = normalize_columns(hist)
            closes = df["close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            spark = [float(x) for x in closes.tail(20).tolist()]
        return {
            "symbol": symbol,
            "name": name,
            "price": q["price"],
            "change_pct": q["change_pct"],
            "sparkline": spark,
        }
    except Exception:
        return {
            "symbol": symbol,
            "name": name,
            "price": q["price"],
            "change_pct": q["change_pct"],
            "sparkline": [q["price"]],
        }


def batch_etf_snapshots(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(etf_snapshot, sym, name) for sym, name in pairs]
        for fut in as_completed(futs):
            snap = fut.result()
            if snap:
                rows.append(snap)
    order = {p[0]: i for i, p in enumerate(pairs)}
    rows.sort(key=lambda r: order.get(r["symbol"], 99))
    return rows


def sector_rows() -> list[dict[str, Any]]:
    """Sector ETF performance + leading stock quote."""
    from core.sector_tracker import SectorTracker

    rel = SectorTracker.get_relative_strength("5d")
    etf_quotes = batch_quotes(list(SECTOR_LEAD_STOCKS.keys()) + [s[1] for s in SECTOR_LEAD_STOCKS.values()])
    rows: list[dict[str, Any]] = []
    for etf, (name, lead) in SECTOR_LEAD_STOCKS.items():
        perf = SectorTracker._period_return_pct(etf, "5d")
        lead_q = etf_quotes.get(lead) or _empty_quote(lead)
        rows.append({
            "symbol": etf,
            "name": name,
            "change_pct": round(float(perf or lead_q["change_pct"]), 2),
            "vs_spy": round(float(rel.get(name, 0)), 2),
            "lead_stock": lead,
            "lead_price": lead_q["price"],
            "lead_change_pct": lead_q["change_pct"],
        })
    rows.sort(key=lambda x: x["change_pct"], reverse=True)
    return rows[:11]
