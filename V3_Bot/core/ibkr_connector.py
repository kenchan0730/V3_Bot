# core/ibkr_connector.py
from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder
import time
import logging
import pandas as pd
logger = logging.getLogger(__name__)

class IBKRConnector:
    def __init__(self, host="127.0.0.1", port=7497, client_id=1, max_retries=10):
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id
        self.max_retries = max_retries
        self.connected = False
        self.positions = {}

    def connect(self):
        retry = 0
        delay = 1
        while retry < self.max_retries:
            try:
                self.ib.connect(self.host, self.port, clientId=self.client_id)
                self.connected = True
                logger.info(f"✅ IBKR 連線成功 (Port: {self.port})")
                self.sync_positions()
                return True
            except Exception as e:
                logger.warning(f"⚠️ 連線失敗 ({retry+1}/{self.max_retries}): {e}")
                time.sleep(delay)
                delay = min(delay * 2, 30)
                retry += 1
        return False

    def disconnect(self):
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            logger.info("已斷開 IBKR 連線")

    def sync_positions(self):
        try:
            positions = self.ib.positions()
            self.positions = {p.contract.symbol: p.position for p in positions}
            logger.info(f"📦 持倉同步完成: {self.positions}")
        except Exception as e:
            logger.error(f"⚠️ 持倉同步失敗: {e}")

    def is_connected(self):
        return self.connected and self.ib.isConnected()

    def get_historical_data(self, symbol, duration="3 M", bar_size="1 day"):
        if not self.connected:
            return None
        contract = Stock(symbol, "SMART", "USD")
        try:
            bars = self.ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                keepUpToDate=False,
                timeout=15
            )
            if not bars:
                return None
            data = []
            for bar in bars:
                data.append({
                    "date": bar.date,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume
                })
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            logger.error(f"歷史數據獲取失敗: {e}")
            return None

    def place_order_with_retry(self, symbol, action, quantity, order_type="LMT", limit_price=None, stop_price=None):
        contract = Stock(symbol, "SMART", "USD")
        order = self._build_order(action, quantity, order_type, limit_price, stop_price)
        for attempt in range(2):
            try:
                trade = self.ib.placeOrder(contract, order)
                logger.info(f"📊 下單成功: {action} {quantity}股 {symbol}")
                return trade
            except Exception as e:
                logger.warning(f"⚠️ 下單失敗 (嘗試 {attempt+1}): {e}")
                if attempt == 0:
                    self.connect()
        return None

    def _build_order(self, action, quantity, order_type, limit_price, stop_price):
        if order_type == "MKT":
            return MarketOrder(action, quantity)
        elif order_type == "LMT":
            return LimitOrder(action, quantity, limit_price)
        elif order_type == "STP":
            return StopOrder(action, quantity, stop_price)
        else:
            return LimitOrder(action, quantity, limit_price)