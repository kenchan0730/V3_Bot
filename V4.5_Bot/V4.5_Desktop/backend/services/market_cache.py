"""Shared TTL cache and batch market quotes for V4.5 Desktop."""

from __future__ import annotations

import logging
import time
from typing import Any

import yfinance as yf

from core.data_utils import normalize_columns

logger = logging.getLogger(__name__)


class TTLCache:
    def __init__(self, ttl_seconds: float = 60.0):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
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


def batch_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch last close and daily change for many symbols in one yfinance call."""
    unique = list(dict.fromkeys(s.upper() for s in symbols if s))
    if not unique:
        return {}

    out: dict[str, dict[str, Any]] = {s: _empty_quote(s) for s in unique}

    if len(unique) == 1:
        sym = unique[0]
        try:
            raw = yf.download(sym, period="5d", interval="1d", progress=False, auto_adjust=True)
            if raw is None or raw.empty:
                return out
            df = normalize_columns(raw)
            closes = df["close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            if len(closes) < 1:
                return out
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else last
            chg = ((last - prev) / prev * 100) if prev else 0.0
            out[sym] = {
                "symbol": sym,
                "price": round(last, 2),
                "change_pct": round(chg, 2),
                "direction": "up" if chg >= 0 else "down",
            }
        except Exception as exc:
            logger.debug("quote %s: %s", sym, exc)
        return out

    try:
        raw = yf.download(
            unique,
            period="5d",
            interval="1d",
            progress=False,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
        )
    except Exception as exc:
        logger.warning("batch_quotes failed: %s", exc)
        return out

    if raw is None or raw.empty:
        return out

    for sym in unique:
        try:
            if sym in raw.columns.get_level_values(0):
                sub = raw[sym]
            else:
                continue
            sub = normalize_columns(sub)
            closes = sub["close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            if len(closes) < 1:
                continue
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) > 1 else last
            chg = ((last - prev) / prev * 100) if prev else 0.0
            out[sym] = {
                "symbol": sym,
                "price": round(last, 2),
                "change_pct": round(chg, 2),
                "direction": "up" if chg >= 0 else "down",
            }
        except Exception as exc:
            logger.debug("quote parse %s: %s", sym, exc)

    return out


def etf_snapshot(symbol: str, name: str) -> dict[str, Any] | None:
    try:
        raw = yf.download(symbol, period="5d", interval="1d", progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return None
        df = normalize_columns(raw)
        closes = df["close"]
        if hasattr(closes, "columns"):
            closes = closes.iloc[:, 0]
        first = float(closes.iloc[0])
        last = float(closes.iloc[-1])
        chg = (last / first - 1) * 100 if first else 0
        spark = [float(x) for x in closes.tail(20).tolist()]
        return {
            "symbol": symbol,
            "name": name,
            "price": round(last, 2),
            "change_pct": round(chg, 2),
            "sparkline": spark,
        }
    except Exception as exc:
        logger.debug("etf %s: %s", symbol, exc)
        return None


def batch_etf_snapshots(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    symbols = [p[0] for p in pairs]
    name_map = dict(pairs)
    rows: list[dict[str, Any]] = []
    try:
        raw = yf.download(
            symbols,
            period="5d",
            interval="1d",
            progress=False,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
        )
    except Exception as exc:
        logger.warning("batch etf failed: %s", exc)
        raw = None

    if raw is None or raw.empty:
        for sym, name in pairs:
            snap = etf_snapshot(sym, name)
            if snap:
                rows.append(snap)
        return rows

    for sym, name in pairs:
        try:
            if sym not in raw.columns.get_level_values(0):
                continue
            sub = normalize_columns(raw[sym])
            closes = sub["close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            if len(closes) < 1:
                continue
            first = float(closes.iloc[0])
            last = float(closes.iloc[-1])
            chg = (last / first - 1) * 100 if first else 0
            spark = [float(x) for x in closes.tail(20).tolist()]
            rows.append({
                "symbol": sym,
                "name": name,
                "price": round(last, 2),
                "change_pct": round(chg, 2),
                "sparkline": spark,
            })
        except Exception as exc:
            logger.debug("etf parse %s: %s", sym, exc)
    return rows
