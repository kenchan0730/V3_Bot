"""Behavioural guardrails. Counters live in TradingState so they cannot drift
out of sync with RiskManager.
"""

from datetime import datetime

from core.trading_state import TradingState


class EmotionManager:
    def __init__(self, state=None, max_daily_trades=3, max_loss_streak=3, config=None):
        cfg = config or {}
        self.state = state if state is not None else TradingState()
        self.max_daily_trades = int(cfg.get("max_daily_trades", max_daily_trades))
        self.max_loss_streak = int(cfg.get("max_loss_streak", max_loss_streak))
        self.monthly_loss = 0.0

    @property
    def consecutive_losses(self):
        return self.state.consecutive_losses

    @consecutive_losses.setter
    def consecutive_losses(self, value):
        self.state.consecutive_losses = int(value)

    @property
    def today_trades(self):
        return self.state.today_trades

    @today_trades.setter
    def today_trades(self, value):
        self.state.today_trades = int(value)

    def record_trade(self, pnl):
        if pnl < 0:
            self.state.consecutive_losses += 1
        elif pnl > 0:
            self.state.consecutive_losses = 0
        self.state.today_trades += 1

    def check_before_trade(self):
        if self.state.consecutive_losses >= self.max_loss_streak:
            return False, f"連續 {self.state.consecutive_losses} 次止蝕，強制休息"
        if self.state.today_trades >= self.max_daily_trades:
            return False, f"今日已交易 {self.state.today_trades} 次，暫停"
        return True, "情緒正常"

    def reset_daily(self):
        self.state.reset_daily_if_needed(datetime.now().date())
