"""Sector relative strength vs SPY, used to scale overall exposure."""

import logging

import yfinance as yf

from core.data_utils import normalize_columns

logger = logging.getLogger(__name__)


class SectorTracker:
    SECTORS = {
        "XLK": "Technology",
        "XLE": "Energy",
        "XLV": "Healthcare",
        "SMH": "Semiconductor",
    }

    @staticmethod
    def _period_return_pct(symbol, period):
        """Percentage change over the period, or None when unavailable.

        Handles yfinance's MultiIndex columns, which otherwise yield a Series
        and break scalar comparisons.
        """
        try:
            raw = yf.download(symbol, period=period, interval="1d", progress=False)
            if raw is None or len(raw) < 2:
                return None
            df = normalize_columns(raw)
            if "close" not in df.columns:
                return None
            closes = df["close"]
            if hasattr(closes, "columns"):  # still 2-D after flattening
                closes = closes.iloc[:, 0]
            first = float(closes.iloc[0])
            last = float(closes.iloc[-1])
            if first == 0:
                return None
            return (last / first - 1) * 100
        except Exception as e:
            logger.warning(f"{symbol} 期間報酬計算失敗: {e}")
            return None

    @staticmethod
    def get_relative_strength(period="5d"):
        """Return {sector_name: outperformance_vs_spy_pct}."""
        spy = SectorTracker._period_return_pct("SPY", period)
        if spy is None:
            spy = 0.0

        relative = {}
        for etf, name in SectorTracker.SECTORS.items():
            performance = SectorTracker._period_return_pct(etf, period)
            relative[name] = 0 if performance is None else round(performance - spy, 2)
        return relative

    @staticmethod
    def get_sector_rating():
        """Convert relative strength into exposure weights plus alerts."""
        rel_5d = SectorTracker.get_relative_strength("5d")
        rel_10d = SectorTracker.get_relative_strength("10d")

        weights, alerts = {}, []
        for sector in SectorTracker.SECTORS.values():
            average = (rel_5d.get(sector, 0) + rel_10d.get(sector, 0)) / 2
            weights[sector] = 100 if average > -1 else max(100 - abs(average) * 12, 50)

        if weights.get("Semiconductor", 100) < weights.get("Technology", 100) - 15:
            alerts.append("SMH 跑輸 XLK，半導體內部出現問題")

        return {"weights": weights, "alerts": alerts}
