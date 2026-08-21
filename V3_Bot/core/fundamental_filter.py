# core/fundamental_filter.py
import yfinance as yf
import logging

logger = logging.getLogger(__name__)

class FundamentalFilter:
    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.min_market_cap = self.config.get("min_market_cap", 500_000_000)
        self.min_avg_volume = self.config.get("min_avg_volume", 1_000_000)
        self.max_pe = self.config.get("max_pe", 30)
        self.min_earnings_growth = self.config.get("min_earnings_growth", 10)
        self.exclude_negative_eps = self.config.get("exclude_negative_eps", True)

    def filter(self, symbol):
        """执行基本面过滤，回传 (通过, 原因)"""
        if not self.enabled:
            return True, "基本面过滤已关闭"

        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            # 1. 市值检查
            market_cap = info.get("marketCap", 0)
            if market_cap < self.min_market_cap:
                return False, f"市值 ${market_cap/1e9:.1f}B < ${self.min_market_cap/1e9:.1f}B"

            # 2. 成交量检查
            avg_volume = info.get("averageVolume", 0)
            if avg_volume < self.min_avg_volume:
                return False, f"日均成交量 {avg_volume:,.0f} < {self.min_avg_volume:,.0f}"

            # 3. 市盈率检查
            pe = info.get("trailingPE", float('inf'))
            if pe == float('inf') or pe is None:
                if self.exclude_negative_eps:
                    return False, "亏损股（无市盈率）"
            elif pe > self.max_pe:
                return False, f"市盈率 {pe:.1f} > {self.max_pe}"

            # 4. 盈利增长检查
            earnings_growth = info.get("earningsGrowth", 0)
            if earnings_growth is not None:
                if earnings_growth < self.min_earnings_growth / 100:
                    return False, f"盈利增长 {earnings_growth*100:.1f}% < {self.min_earnings_growth}%"

            return True, "✅ 基本面合格"

        except Exception as e:
            logger.warning(f"基本面检查失败 {symbol}: {e}")
            return True, f"⚠️ 基本面检查跳过（{e}）"

    def get_earnings_surprise(self, symbol):
        """获取最近 EPS 惊喜（超预期百分比）"""
        try:
            ticker = yf.Ticker(symbol)
            earnings = ticker.earnings
            if earnings is not None and not earnings.empty:
                latest = earnings.iloc[-1]
                actual = latest.get("actual", 0)
                estimate = latest.get("estimate", 0)
                if estimate and estimate != 0:
                    surprise = ((actual - estimate) / abs(estimate)) * 100
                    return round(surprise, 1)
            return None
        except:
            return None

    def get_earnings_date(self, symbol):
        """获取下一个财报日期"""
        try:
            ticker = yf.Ticker(symbol)
            calendar = ticker.calendar
            if calendar is not None and not calendar.empty:
                if "Earnings Date" in calendar:
                    return calendar["Earnings Date"]
            return None
        except:
            return None