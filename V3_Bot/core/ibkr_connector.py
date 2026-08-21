"""Interactive Brokers connectivity: market data, account state, and orders.

Adds bracket (OCA) orders, position/P&L reconciliation, buying-power checks and
order cancellation on top of the original connector.
"""

import logging
import time

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder

    IB_AVAILABLE = True
except ImportError:
    # ib_insync is optional: without it the connector cannot reach a broker
    # (connect() returns False), but it stays importable and unit-testable with
    # an injected IB double. These stubs only describe order intent.
    IB = None
    IB_AVAILABLE = False

    class _StubContract:
        def __init__(self, symbol, exchange="SMART", currency="USD"):
            self.symbol = symbol
            self.exchange = exchange
            self.currency = currency

    class _StubOrder:
        _next_id = 1

        def __init__(self, action, quantity, order_type, price=None):
            self.action = action
            self.totalQuantity = quantity
            self.orderType = order_type
            self.lmtPrice = price if order_type == "LMT" else None
            self.auxPrice = price if order_type == "STP" else None
            self.orderId = _StubOrder._next_id
            _StubOrder._next_id += 1
            self.parentId = None
            self.transmit = True

    def Stock(symbol, exchange="SMART", currency="USD"):
        return _StubContract(symbol, exchange, currency)

    def MarketOrder(action, quantity):
        return _StubOrder(action, quantity, "MKT")

    def LimitOrder(action, quantity, price):
        return _StubOrder(action, quantity, "LMT", price)

    def StopOrder(action, quantity, price):
        return _StubOrder(action, quantity, "STP", price)


class IBKRConnector:
    def __init__(self, host="127.0.0.1", port=7497, client_id=1, max_retries=10,
                 account_mode="paper", ib=None):
        if ib is not None:
            self.ib = ib
        elif IB_AVAILABLE:
            self.ib = IB()
        else:
            self.ib = None
            logger.warning("ib_insync 未安裝，IBKR 功能停用")

        self.host = host
        self.port = int(port)
        self.client_id = int(client_id)
        self.max_retries = max_retries
        self.account_mode = str(account_mode).lower()
        self.connected = False
        self.positions = {}
        self._last_account_values = {}

    # ----- lifecycle -----

    def connect(self):
        if self.ib is None:
            return False
        if self.account_mode == "live" and self.port in (7497, 4002):
            logger.warning("account_mode=live 但連接埠看似模擬盤，請確認設定")
        if self.account_mode == "paper" and self.port in (7496, 4001):
            logger.error("account_mode=paper 但連接埠是實盤，拒絕連線")
            return False

        retry, delay = 0, 1
        while retry < self.max_retries:
            try:
                self.ib.connect(self.host, self.port, clientId=self.client_id)
                self.connected = True
                logger.info(f"✅ IBKR 連線成功 (Port: {self.port}, mode: {self.account_mode})")
                self.sync_positions()
                return True
            except Exception as e:
                logger.warning(f"⚠️ 連線失敗 ({retry + 1}/{self.max_retries}): {e}")
                time.sleep(delay)
                delay = min(delay * 2, 30)
                retry += 1
        return False

    def disconnect(self):
        if self.connected and self.ib is not None:
            try:
                self.ib.disconnect()
            finally:
                self.connected = False
                logger.info("已斷開 IBKR 連線")

    def is_connected(self):
        if self.ib is None:
            return False
        try:
            return bool(self.connected and self.ib.isConnected())
        except Exception:
            return False

    # ----- account & positions -----

    def sync_positions(self):
        """Refresh the local position map from the broker."""
        if self.ib is None:
            return {}
        try:
            positions = {}
            for p in self.ib.positions():
                symbol = p.contract.symbol
                positions[symbol] = {
                    "quantity": float(p.position),
                    "avg_cost": float(getattr(p, "avgCost", 0) or 0),
                }
            self.positions = positions
            logger.info(f"📦 持倉同步完成: {positions}")
            return positions
        except Exception as e:
            logger.error(f"⚠️ 持倉同步失敗: {e}")
            return self.positions

    def get_positions(self):
        return self.sync_positions()

    def get_account_values(self):
        """Return net liquidation, buying power and available funds."""
        if self.ib is None:
            return {}
        try:
            values = {}
            for row in self.ib.accountSummary():
                if row.tag in ("NetLiquidation", "BuyingPower", "AvailableFunds", "TotalCashValue"):
                    try:
                        values[row.tag] = float(row.value)
                    except (TypeError, ValueError):
                        continue
            self._last_account_values = {
                "net_liquidation": values.get("NetLiquidation", 0.0),
                "buying_power": values.get("BuyingPower", 0.0),
                "available_funds": values.get("AvailableFunds", 0.0),
                "cash": values.get("TotalCashValue", 0.0),
            }
            return self._last_account_values
        except Exception as e:
            logger.error(f"帳戶資訊獲取失敗: {e}")
            return self._last_account_values

    def get_buying_power(self):
        return float(self.get_account_values().get("buying_power", 0.0) or 0.0)

    def get_realized_pnl_since(self, seen_exec_ids=None):
        """Sum realised P&L from fills not yet accounted for.

        Returns (total_realized, new_exec_ids, fill_details).
        """
        seen = set(seen_exec_ids or [])
        total, new_ids, details = 0.0, [], []
        if self.ib is None:
            return total, new_ids, details
        try:
            for fill in self.ib.fills():
                execution = getattr(fill, "execution", None)
                report = getattr(fill, "commissionReport", None)
                exec_id = getattr(execution, "execId", None)
                if not exec_id or exec_id in seen:
                    continue
                realized = getattr(report, "realizedPNL", 0.0) or 0.0
                commission = getattr(report, "commission", 0.0) or 0.0
                try:
                    realized = float(realized)
                except (TypeError, ValueError):
                    realized = 0.0
                if realized in (float("inf"), float("-inf")) or realized != realized:
                    realized = 0.0
                total += realized
                new_ids.append(exec_id)
                details.append({
                    "exec_id": exec_id,
                    "symbol": getattr(getattr(fill, "contract", None), "symbol", ""),
                    "side": getattr(execution, "side", ""),
                    "shares": float(getattr(execution, "shares", 0) or 0),
                    "price": float(getattr(execution, "price", 0) or 0),
                    "realized_pnl": realized,
                    "commission": float(commission or 0),
                })
        except Exception as e:
            logger.error(f"成交紀錄讀取失敗: {e}")
        return total, new_ids, details

    # ----- market data -----

    def get_historical_data(self, symbol, duration="3 M", bar_size="1 day"):
        if not self.connected or self.ib is None:
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
                timeout=15,
            )
            if not bars:
                return None
            data = [{
                "date": bar.date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            } for bar in bars]
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception as e:
            logger.error(f"歷史數據獲取失敗: {e}")
            return None

    # ----- orders -----

    def place_bracket_order(self, symbol, quantity, entry_price, stop_price, target_price, action="BUY"):
        """Submit a limit entry with attached stop-loss and take-profit children.

        The stop always reaches the broker, so protection survives a bot crash.
        """
        if self.ib is None or not self.connected:
            logger.error("未連線，無法下單")
            return None
        if quantity <= 0:
            logger.error("下單數量必須大於 0")
            return None
        if not stop_price or stop_price <= 0:
            logger.error("拒絕無停損的訂單")
            return None

        contract = Stock(symbol, "SMART", "USD")
        try:
            orders = self._build_bracket(action, quantity, entry_price, target_price, stop_price)
            trades = []
            for order in orders:
                trades.append(self.ib.placeOrder(contract, order))
            parent_id = getattr(orders[0], "orderId", None)
            logger.info(
                f"📊 Bracket 已送出: {action} {quantity} {symbol} @ {entry_price} "
                f"| 停損 {stop_price} | 目標 {target_price} | parent={parent_id}"
            )
            return {
                "parent_id": parent_id,
                "trades": trades,
                "symbol": symbol,
                "quantity": quantity,
                "entry": entry_price,
                "stop": stop_price,
                "target": target_price,
                "action": action,
            }
        except Exception as e:
            logger.error(f"Bracket 下單失敗 {symbol}: {e}")
            return None

    def _build_bracket(self, action, quantity, entry_price, target_price, stop_price):
        """Prefer ib_insync's bracketOrder; fall back to manual OCA construction."""
        if hasattr(self.ib, "bracketOrder"):
            try:
                bracket = self.ib.bracketOrder(
                    action, quantity,
                    limitPrice=entry_price,
                    takeProfitPrice=target_price,
                    stopLossPrice=stop_price,
                )
                return list(bracket)
            except Exception as e:
                logger.warning(f"bracketOrder 不可用，改用手動建構: {e}")

        exit_action = "SELL" if action.upper() == "BUY" else "BUY"
        parent = LimitOrder(action, quantity, entry_price)
        parent.transmit = False
        take_profit = LimitOrder(exit_action, quantity, target_price)
        take_profit.parentId = getattr(parent, "orderId", None)
        take_profit.transmit = False
        stop_loss = StopOrder(exit_action, quantity, stop_price)
        stop_loss.parentId = getattr(parent, "orderId", None)
        stop_loss.transmit = True
        return [parent, take_profit, stop_loss]

    def place_order_with_retry(self, symbol, action, quantity, order_type="LMT",
                              limit_price=None, stop_price=None):
        """Single-leg order. Prefer place_bracket_order for entries."""
        if self.ib is None or not self.connected:
            return None
        contract = Stock(symbol, "SMART", "USD")
        order = self._build_order(action, quantity, order_type, limit_price, stop_price)
        for attempt in range(2):
            try:
                trade = self.ib.placeOrder(contract, order)
                logger.info(f"📊 下單成功: {action} {quantity}股 {symbol}")
                return trade
            except Exception as e:
                logger.warning(f"⚠️ 下單失敗 (嘗試 {attempt + 1}): {e}")
                if attempt == 0:
                    self.connect()
        return None

    def _build_order(self, action, quantity, order_type, limit_price, stop_price):
        if order_type == "MKT":
            return MarketOrder(action, quantity)
        if order_type == "STP":
            return StopOrder(action, quantity, stop_price)
        return LimitOrder(action, quantity, limit_price)

    def get_open_orders(self):
        if self.ib is None:
            return []
        try:
            return list(self.ib.openTrades())
        except Exception as e:
            logger.error(f"未成交訂單讀取失敗: {e}")
            return []

    def cancel_order(self, order):
        if self.ib is None:
            return False
        try:
            self.ib.cancelOrder(order)
            return True
        except Exception as e:
            logger.error(f"取消訂單失敗: {e}")
            return False

    def cancel_orders_for_symbol(self, symbol):
        """Cancel every working order on a symbol (e.g. before a manual exit)."""
        cancelled = 0
        for trade in self.get_open_orders():
            trade_symbol = getattr(getattr(trade, "contract", None), "symbol", None)
            if trade_symbol != symbol:
                continue
            if self.cancel_order(getattr(trade, "order", trade)):
                cancelled += 1
        if cancelled:
            logger.info(f"🚫 已取消 {symbol} 的 {cancelled} 筆掛單")
        return cancelled

    def close_position(self, symbol, limit_price=None):
        """Cancel working orders then flatten the position."""
        positions = self.sync_positions()
        quantity = float(positions.get(symbol, {}).get("quantity", 0) or 0)
        if quantity == 0:
            logger.info(f"{symbol} 無持倉，略過平倉")
            return None

        self.cancel_orders_for_symbol(symbol)
        action = "SELL" if quantity > 0 else "BUY"
        order_type = "LMT" if limit_price else "MKT"
        logger.info(f"🔻 平倉 {symbol}: {action} {abs(quantity)} 股 ({order_type})")
        return self.place_order_with_retry(
            symbol, action, int(abs(quantity)), order_type=order_type, limit_price=limit_price
        )
