"""Universe builder for dynamic watchlists — free data only (Wikipedia + yfinance)."""

import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

FALLBACK_POOL = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "JPM", "JNJ", "WMT", "PG",
    "MA", "UNH", "HD", "DIS", "ADBE", "NFLX", "CRM", "AMD", "TSLA",
    "BAC", "WFC", "PFE", "CVX", "XOM", "ABT", "TMO", "AVGO", "TXN",
    "QCOM", "COST", "NKE", "IBM", "ORCL", "CSCO", "PEP", "MCD", "ABBV",
    "MRK", "T", "F", "PLUG", "SOFI", "PLTR", "NIO", "SNAP", "HOOD",
    "RIVN", "LCID", "AAL", "DAL", "UAL", "INTC", "MU", "ON", "SMCI",
]


class ScannerPool:
    DEFAULTS = {
        "enabled": True,
        "source": "sp500",
        "max_scan": 150,
        "min_price": 5.0,
        "max_price": 40.0,
        "min_market_cap": 500_000_000,
        "min_avg_volume": 500_000,
    }

    def __init__(self, config=None):
        self.cfg = {**self.DEFAULTS, **(config or {})}

    def get_universe(self):
        if not self.cfg.get("enabled", True):
            return []
        source = self.cfg.get("source", "sp500").lower()
        if source == "fallback":
            return list(FALLBACK_POOL)
        try:
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            table = pd.read_html(url)[0]
            symbols = [str(s).replace(".", "-") for s in table["Symbol"].tolist()]
            logger.info(f"ScannerPool: loaded {len(symbols)} S&P 500 symbols")
            return symbols
        except Exception as exc:
            logger.warning(f"S&P 500 fetch failed ({exc}); using fallback pool")
            return list(FALLBACK_POOL)

    def prefilter(self, symbol):
        try:
            info = yf.Ticker(symbol).info or {}
            price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
            if price <= 0:
                return False, "no price"
            if price < self.cfg["min_price"] or price > self.cfg["max_price"]:
                return False, "price band"
            cap = info.get("marketCap") or 0
            if cap < self.cfg["min_market_cap"]:
                return False, "market cap"
            vol = info.get("averageVolume") or info.get("averageVolume10days") or 0
            if vol < self.cfg["min_avg_volume"]:
                return False, "volume"
            return True, "OK"
        except Exception:
            return False, "error"

    def scan(self, limit=None):
        pool = self.get_universe()
        max_scan = int(limit or self.cfg.get("max_scan", 150))
        candidates = []
        for symbol in pool[: max_scan * 3]:
            if len(candidates) >= max_scan:
                break
            ok, _ = self.prefilter(symbol)
            if ok:
                candidates.append(symbol.upper())
        logger.info(f"ScannerPool: {len(candidates)} candidates from {min(len(pool), max_scan * 3)} scanned")
        return candidates
