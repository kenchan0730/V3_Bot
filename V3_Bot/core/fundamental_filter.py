# core/fundamental_filter.py
import logging
import time

import yfinance as yf

logger = logging.getLogger(__name__)


class FundamentalFilter:
    """yfinance fundamentals gate with a TTL cache to limit network calls."""

    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.min_market_cap = self.config.get("min_market_cap", 500_000_000)
        self.min_avg_volume = self.config.get("min_avg_volume", 1_000_000)
        self.max_pe = self.config.get("max_pe", 30)
        self.min_earnings_growth = self.config.get("min_earnings_growth", 10)
        self.exclude_negative_eps = self.config.get("exclude_negative_eps", True)
        self.cache_ttl_seconds = int(self.config.get("cache_ttl_seconds", 86400))
        self._cache = {}

    def _get_info(self, symbol):
        """Return cached fundamentals, refreshing once the TTL expires."""
        cached = self._cache.get(symbol)
        now = time.time()
        if cached and now - cached["fetched_at"] < self.cache_ttl_seconds:
            return cached["info"]
        info = yf.Ticker(symbol).info
        self._cache[symbol] = {"info": info, "fetched_at": now}
        return info

    def clear_cache(self, symbol=None):
        if symbol:
            self._cache.pop(symbol, None)
        else:
            self._cache.clear()

    def filter(self, symbol):
        """Return (passed, reason)."""
        if not self.enabled:
            return True, "基本面過濾已關閉"

        try:
            info = self._get_info(symbol)

            market_cap = info.get("marketCap", 0) or 0
            if market_cap < self.min_market_cap:
                return False, f"市值 ${market_cap / 1e9:.1f}B < ${self.min_market_cap / 1e9:.1f}B"

            avg_volume = info.get("averageVolume", 0) or 0
            if avg_volume < self.min_avg_volume:
                return False, f"日均成交量 {avg_volume:,.0f} < {self.min_avg_volume:,.0f}"

            pe = info.get("trailingPE", float("inf"))
            if pe == float("inf") or pe is None:
                if self.exclude_negative_eps:
                    return False, "虧損股（無市盈率）"
            elif pe > self.max_pe:
                return False, f"市盈率 {pe:.1f} > {self.max_pe}"

            earnings_growth = info.get("earningsGrowth", 0)
            if earnings_growth is not None:
                if earnings_growth < self.min_earnings_growth / 100:
                    return False, f"盈利增長 {earnings_growth * 100:.1f}% < {self.min_earnings_growth}%"

            return True, "✅ 基本面合格"

        except Exception as e:
            logger.warning(f"基本面檢查失敗 {symbol}: {e}")
            return True, f"⚠️ 基本面檢查跳過（{e}）"

    def get_earnings_date(self, symbol):
        try:
            calendar = yf.Ticker(symbol).calendar
            if calendar is not None and len(calendar) and "Earnings Date" in calendar:
                return calendar["Earnings Date"]
            return None
        except Exception:
            return None
