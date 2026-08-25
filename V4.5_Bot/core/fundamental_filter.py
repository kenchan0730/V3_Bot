"""Fundamentals gate with two personalities.

``institutional`` mode is the original veto list: a single failed metric blocks
the name. That is correct for a mandate-bound book, but it also removed almost
every candidate a small account would actually trade — unprofitable growth
names, high-multiple compounders, recent turnarounds.

``retail`` mode keeps the same measurements but converts them into a quality
tier (A–D). Only genuine retail hazards — micro caps and illiquid tape — are
hard vetoes; everything else is priced in downstream by ``RetailMind`` (a C-tier
name needs a live catalyst, and gets a smaller position).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import yfinance as yf

logger = logging.getLogger(__name__)

TIER_LABELS = {
    "A": "獲利穩健、估值合理",
    "B": "可接受，但估值或成長偏弱",
    "C": "虧損或估值極高 — 需催化劑",
    "D": "微型股／流動性不足 — 散戶亦不宜",
}


@dataclass
class FundamentalView:
    symbol: str
    passed: bool = True
    tier: str = "B"
    reason: str = ""
    reasons: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "passed": self.passed,
            "tier": self.tier,
            "tier_label": TIER_LABELS.get(self.tier, ""),
            "reason": self.reason,
            "reasons": self.reasons,
            "flags": self.flags,
            "metrics": self.metrics,
        }


class FundamentalFilter:
    """yfinance fundamentals gate with a TTL cache to limit network calls."""

    RETAIL_DEFAULTS = {
        "min_market_cap": 150_000_000,
        "min_avg_volume": 400_000,
        "extreme_pe": 80.0,
        "allow_unprofitable": True,
    }

    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.mode = str(self.config.get("mode", "institutional")).lower()
        self.min_market_cap = self.config.get("min_market_cap", 500_000_000)
        self.min_avg_volume = self.config.get("min_avg_volume", 1_000_000)
        self.max_pe = self.config.get("max_pe", 30)
        self.min_earnings_growth = self.config.get("min_earnings_growth", 10)
        self.exclude_negative_eps = self.config.get("exclude_negative_eps", True)
        self.cache_ttl_seconds = int(self.config.get("cache_ttl_seconds", 86400))
        self.retail = {**self.RETAIL_DEFAULTS, **(self.config.get("retail") or {})}
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

    # ----- shared metric extraction -----

    @staticmethod
    def _metrics(info):
        def num(key):
            value = info.get(key)
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        return {
            "market_cap": num("marketCap") or 0.0,
            "avg_volume": num("averageVolume") or 0.0,
            "trailing_pe": num("trailingPE"),
            "forward_pe": num("forwardPE"),
            "earnings_growth": num("earningsGrowth"),
            "revenue_growth": num("revenueGrowth"),
            "profit_margins": num("profitMargins"),
            "debt_to_equity": num("debtToEquity"),
            "beta": num("beta"),
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "Unknown",
        }

    def _accuracy_flags(self, metrics):
        """Data-quality notes a desk would raise before trusting these numbers."""
        flags = []
        if not metrics.get("market_cap"):
            flags.append("市值資料缺失（yfinance 回傳 0）— 數據可能不準")
        if metrics.get("trailing_pe") is None and metrics.get("forward_pe") is None:
            flags.append("無任何市盈率資料")
        trailing, forward = metrics.get("trailing_pe"), metrics.get("forward_pe")
        if trailing and forward and forward > 0 and trailing / forward > 2.5:
            flags.append(
                f"trailing PE {trailing:.0f} 遠高於 forward PE {forward:.0f}（市場預期獲利改善）"
            )
        if metrics.get("debt_to_equity") and metrics["debt_to_equity"] > 200:
            flags.append(f"負債權益比 {metrics['debt_to_equity']:.0f}% 偏高")
        if metrics.get("profit_margins") is not None and metrics["profit_margins"] < 0:
            flags.append(f"淨利率 {metrics['profit_margins'] * 100:.1f}%（虧損中）")
        return flags

    # ----- public API -----

    def assess(self, symbol) -> FundamentalView:
        """Full view: pass/fail plus a quality tier and data-accuracy flags."""
        if not self.enabled:
            return FundamentalView(symbol=symbol, passed=True, tier="B", reason="基本面過濾已關閉")

        try:
            info = self._get_info(symbol)
        except Exception as exc:
            logger.warning(f"基本面檢查失敗 {symbol}: {exc}")
            return FundamentalView(
                symbol=symbol, passed=True, tier="B",
                reason=f"⚠️ 基本面檢查跳過（{exc}）",
                flags=["資料取得失敗，未做基本面驗證"],
            )

        metrics = self._metrics(info)
        flags = self._accuracy_flags(metrics)
        if self.mode == "retail":
            view = self._assess_retail(symbol, metrics)
        else:
            view = self._assess_institutional(symbol, metrics)
        view.flags = flags
        view.metrics = metrics
        return view

    def filter(self, symbol):
        """Return (passed, reason) — kept for existing call sites."""
        view = self.assess(symbol)
        return view.passed, view.reason

    # ----- mode implementations -----

    def _assess_institutional(self, symbol, m) -> FundamentalView:
        if m["market_cap"] < self.min_market_cap:
            return FundamentalView(
                symbol=symbol, passed=False, tier="D",
                reason=f"市值 ${m['market_cap'] / 1e9:.1f}B < ${self.min_market_cap / 1e9:.1f}B",
            )
        if m["avg_volume"] < self.min_avg_volume:
            return FundamentalView(
                symbol=symbol, passed=False, tier="D",
                reason=f"日均成交量 {m['avg_volume']:,.0f} < {self.min_avg_volume:,.0f}",
            )

        pe = m["trailing_pe"]
        if pe is None:
            if self.exclude_negative_eps:
                return FundamentalView(
                    symbol=symbol, passed=False, tier="C", reason="虧損股（無市盈率）",
                )
        elif pe > self.max_pe:
            return FundamentalView(
                symbol=symbol, passed=False, tier="B",
                reason=f"市盈率 {pe:.1f} > {self.max_pe}",
            )

        growth = m["earnings_growth"]
        if growth is not None and growth < self.min_earnings_growth / 100:
            return FundamentalView(
                symbol=symbol, passed=False, tier="B",
                reason=f"盈利增長 {growth * 100:.1f}% < {self.min_earnings_growth}%",
            )

        return FundamentalView(symbol=symbol, passed=True, tier="A", reason="✅ 基本面合格")

    def _assess_retail(self, symbol, m) -> FundamentalView:
        """Tier the name; veto only what a retail account genuinely cannot trade."""
        min_cap = float(self.retail["min_market_cap"])
        min_vol = float(self.retail["min_avg_volume"])

        if m["market_cap"] and m["market_cap"] < min_cap:
            return FundamentalView(
                symbol=symbol, passed=False, tier="D",
                reason=f"市值 ${m['market_cap'] / 1e6:.0f}M < ${min_cap / 1e6:.0f}M（微型股）",
            )
        if m["avg_volume"] and m["avg_volume"] < min_vol:
            return FundamentalView(
                symbol=symbol, passed=False, tier="D",
                reason=f"日均成交量 {m['avg_volume']:,.0f} < {min_vol:,.0f}（流動性不足）",
            )

        pe = m["trailing_pe"]
        forward = m["forward_pe"]
        growth = m["earnings_growth"]
        extreme_pe = float(self.retail["extreme_pe"])
        reasons = []
        tier = "B"

        profitable = pe is not None and pe > 0
        if not profitable:
            if not self.retail.get("allow_unprofitable", True):
                return FundamentalView(
                    symbol=symbol, passed=False, tier="C",
                    reason="虧損股（設定不允許）",
                )
            tier = "C"
            if forward and 0 < forward <= extreme_pe:
                reasons.append(f"目前虧損，但 forward PE {forward:.0f} 顯示預期轉盈")
            else:
                reasons.append("目前虧損：需要催化劑與動能，不靠估值")
        elif pe > extreme_pe:
            tier = "C"
            reasons.append(f"市盈率 {pe:.0f} 極高（> {extreme_pe:.0f}）")
        elif pe > self.max_pe:
            tier = "B"
            reasons.append(f"市盈率 {pe:.1f} 高於保守上限 {self.max_pe}（成長股常態）")
        else:
            tier = "A"
            reasons.append(f"市盈率 {pe:.1f} 合理")

        if growth is not None:
            if growth >= self.min_earnings_growth / 100:
                reasons.append(f"盈利增長 {growth * 100:.0f}%")
                if tier == "B":
                    tier = "A"
            else:
                reasons.append(f"盈利增長 {growth * 100:.0f}% 偏弱")
                if tier == "A":
                    tier = "B"

        if m["market_cap"] and m["market_cap"] < self.min_market_cap and tier == "A":
            tier = "B"
            reasons.append(f"市值 ${m['market_cap'] / 1e9:.1f}B 屬中小型")

        return FundamentalView(
            symbol=symbol, passed=True, tier=tier,
            reason=f"基本面 {tier} 級（{TIER_LABELS.get(tier, '')}）",
            reasons=reasons,
        )

    def get_earnings_date(self, symbol):
        try:
            calendar = yf.Ticker(symbol).calendar
            if calendar is not None and len(calendar) and "Earnings Date" in calendar:
                return calendar["Earnings Date"]
            return None
        except Exception:
            return None
