"""Sector relative strength vs SPY — exposure scaling and swing sector rotation."""

import logging
from functools import lru_cache

import yfinance as yf

from core.data_utils import normalize_columns

logger = logging.getLogger(__name__)

# GICS sector SPDRs + key sub-sectors
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLY": "Consumer Cyclical",
    "XLP": "Consumer Defensive",
    "XLC": "Communication Services",
    "SMH": "Semiconductor",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
}

# Alias watchlist / yfinance sector strings → canonical sector name
SECTOR_ALIASES = {
    "Financial Services": "Financials",
    "Consumer Disc": "Consumer Cyclical",
    "ConsumerDiscretionary": "Consumer Cyclical",
    "Consumer Cyclical": "Consumer Cyclical",
    "Consumer Defensive": "Consumer Defensive",
    "Consumer Staples": "Consumer Defensive",
    "Industrials": "Industrials",
    "Communication": "Communication Services",
    "Communication Services": "Communication Services",
    "Semiconductor": "Semiconductor",
    "Semiconductors": "Semiconductor",
    "Technology": "Technology",
    "Healthcare": "Healthcare",
    "Health Care": "Healthcare",
    "Energy": "Energy",
    "Unknown": "Unknown",
}


class SectorTracker:
    SECTORS = SECTOR_ETFS

    @staticmethod
    def normalize_sector_name(name: str) -> str:
        return SECTOR_ALIASES.get(name, name)

    @staticmethod
    def _period_return_pct(symbol, period):
        try:
            raw = yf.download(symbol, period=period, interval="1d", progress=False)
            if raw is None or len(raw) < 2:
                return None
            df = normalize_columns(raw)
            if "close" not in df.columns:
                return None
            closes = df["close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            first = float(closes.iloc[0])
            last = float(closes.iloc[-1])
            if first == 0:
                return None
            return (last / first - 1) * 100
        except Exception as exc:
            logger.warning("%s 期間報酬計算失敗: %s", symbol, exc)
            return None

    @staticmethod
    def get_relative_strength(period="5d"):
        spy = SectorTracker._period_return_pct("SPY", period)
        if spy is None:
            spy = 0.0
        relative = {}
        for etf, name in SECTOR_ETFS.items():
            performance = SectorTracker._period_return_pct(etf, period)
            relative[name] = 0 if performance is None else round(performance - spy, 2)
        return relative

    @staticmethod
    def get_leading_sectors(period="1mo", top_n=4):
        rel = SectorTracker.get_relative_strength(period)
        ranked = sorted(rel.items(), key=lambda x: x[1], reverse=True)
        return [name for name, _ in ranked[:top_n]]

    @staticmethod
    def get_sector_rating():
        rel_5d = SectorTracker.get_relative_strength("5d")
        rel_10d = SectorTracker.get_relative_strength("10d")
        weights, alerts = {}, []
        sectors = set(SECTOR_ETFS.values())
        for sector in sectors:
            average = (rel_5d.get(sector, 0) + rel_10d.get(sector, 0)) / 2
            weights[sector] = 100 if average > -1 else max(100 - abs(average) * 12, 50)

        if weights.get("Semiconductor", 100) < weights.get("Technology", 100) - 15:
            alerts.append("SMH 跑輸 XLK，半導體內部出現問題")
        return {"weights": weights, "alerts": alerts}

    @staticmethod
    def get_market_sector_context(period="1mo", top_n=4):
        """Sector rotation snapshot for swing filters and logging."""
        rel = SectorTracker.get_relative_strength(period)
        leading = SectorTracker.get_leading_sectors(period, top_n=top_n)
        tech_rs = rel.get("Technology", 0) + rel.get("Semiconductor", 0)
        defensive = (
            rel.get("Consumer Defensive", 0)
            + rel.get("Utilities", 0)
            + rel.get("Healthcare", 0)
        ) / 3
        if tech_rs > defensive + 1.5:
            theme_hint = "growth/tech"
        elif defensive > tech_rs + 1.0:
            theme_hint = "defensive"
        else:
            theme_hint = "mixed/rotation"

        positive = [s for s, v in rel.items() if v > 0]
        return {
            "relative_strength": rel,
            "leading_sectors": leading,
            "positive_sectors": positive,
            "theme_hint": theme_hint,
            "period": period,
        }
