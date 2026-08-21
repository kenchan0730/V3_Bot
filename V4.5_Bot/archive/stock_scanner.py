# core/stock_scanner.py
import yfinance as yf
import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class StockScanner:
    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)
        self.max_stocks = self.config.get("max_stocks", 200)
        self.min_price = self.config.get("min_price", 5)
        self.max_price = self.config.get("max_price", 40)

    def get_stock_pool(self):
        """获取待扫描的股票池（S&P 500 成分股）"""
        try:
            # 方法 1：从 Wikipedia 获取 S&P 500 列表
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            sp500 = pd.read_html(url)[0]
            stocks = sp500["Symbol"].tolist()
            logger.info(f"📋 获取 S&P 500 股票池: {len(stocks)} 只")
            return stocks
        except Exception as e:
            logger.warning(f"获取 S&P 500 失败 ({e})，使用备用清单")
            return self._get_fallback_pool()

    def _get_fallback_pool(self):
        """备用股票池（如果无法获取完整 S&P 500）"""
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "JPM", "VTI", "JNJ", "WMT", "PG",
            "MA", "UNH", "HD", "DIS", "VZ", "ADBE", "NFLX", "CRM", "AMD", "TSLA",
            "BAC", "WFC", "PFE", "CVX", "XOM", "ABT", "TMO", "AVGO", "TXN", "QCOM",
            "COST", "NKE", "IBM", "ORCL", "CSCO", "PEP", "MCD", "ABBV", "MRK", "T"
        ]

    def prefilter(self, symbol):
        """快速预筛选（只获取基本信息，避免完整下载）"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            price = info.get("regularMarketPrice", 0)
            if price <= 0:
                return False
            
            # 股价范围过滤
            if price < self.min_price or price > self.max_price:
                return False
            
            # 市值过滤（至少 5 亿美元）
            market_cap = info.get("marketCap", 0)
            if market_cap < 500_000_000:
                return False
            
            # 成交量过滤
            volume = info.get("averageVolume", 0)
            if volume < 500_000:
                return False
            
            return True
            
        except:
            return False

    def scan(self):
        """执行全市场扫描，返回符合基本条件的候选股票列表"""
        if not self.enabled:
            return []

        pool = self.get_stock_pool()
        candidates = []
        count = 0

        logger.info(f"🔍 开始扫描 {len(pool)} 只股票...")

        for symbol in pool:
            if self.prefilter(symbol):
                candidates.append(symbol)
                logger.debug(f"   ✅ {symbol} 通过预筛选")
            
            count += 1
            if count >= self.max_stocks:
                break

        logger.info(f"📋 预筛选完成，共 {len(candidates)} 只候选股票")
        return candidates