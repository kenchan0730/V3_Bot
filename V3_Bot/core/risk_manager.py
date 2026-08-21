import logging
from datetime import datetime
import pytz
logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, initial_capital=385.0, max_risk_pct=2.0):
        self.initial_capital = initial_capital
        self.total_capital = initial_capital
        self.max_risk_pct = max_risk_pct
        self.current_risk_pct = max_risk_pct
        self.peak_capital = initial_capital
        self.consecutive_losses = 0
        self.today_trades = 0
        self.daily_loss = 0.0
        self.daily_loss_limit = 2.0  # %

    def update_capital(self, new_capital):
        self.total_capital = new_capital
        if new_capital > self.peak_capital:
            self.peak_capital = new_capital

    def check_drawdown(self):
        if self.peak_capital > 0:
            drawdown = (self.peak_capital - self.total_capital) / self.peak_capital * 100
            if drawdown > 10:
                return False, f"高位回撤 {drawdown:.1f}% > 10%"
        loss_from_initial = (self.initial_capital - self.total_capital) / self.initial_capital * 100
        if loss_from_initial > 8:
            return False, f"絕對虧損 {loss_from_initial:.1f}% > 8%"
        return True, "OK"

    def check_daily_loss(self, pnl):
        self.daily_loss += pnl
        loss_pct = (self.daily_loss / self.total_capital) * 100
        if loss_pct < -self.daily_loss_limit:
            return False, f"今日虧損 {loss_pct:.2f}% 已達限額"
        return True, f"今日虧損 {loss_pct:.2f}%"

    def calculate_position_size(self, entry_price, stop_loss_price, price_limit=40, max_shares=20):
        if entry_price <= stop_loss_price or entry_price > price_limit:
            return 0
        risk_per_share = entry_price - stop_loss_price
        if risk_per_share <= 0:
            return 0
        max_loss = self.total_capital * (self.current_risk_pct / 100.0)
        shares = int(max_loss / risk_per_share)
        cost = shares * entry_price
        if cost > self.total_capital * 0.5:
            shares = int((self.total_capital * 0.5) / entry_price)
        shares = min(shares, max_shares)
        return max(0, shares)

    def record_trade(self, pnl_usd):
        if pnl_usd < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        if self.consecutive_losses >= 3:
            self.current_risk_pct = 1.0
            logger.warning(f"連續3次止蝕，風險降至1%")
        else:
            self.current_risk_pct = self.max_risk_pct
        self.total_capital += pnl_usd
        self.today_trades += 1

    def check_vix(self, vix):
        if vix > 25:
            self.current_risk_pct = min(self.current_risk_pct, 1.5)
        return self.current_risk_pct

    @staticmethod
    def is_market_open():
        et = pytz.timezone("US/Eastern")
        now = datetime.now(et)
        is_weekday = now.weekday() < 5
        is_trading_hour = (9, 30) <= (now.hour, now.minute) < (16, 0)
        return is_weekday and is_trading_hour