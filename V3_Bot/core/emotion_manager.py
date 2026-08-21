from datetime import datetime

class EmotionManager:
    def __init__(self):
        self.consecutive_losses = 0
        self.today_trades = 0
        self.monthly_loss = 0.0

    def record_trade(self, pnl):
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        self.today_trades += 1

    def check_before_trade(self):
        if self.consecutive_losses >= 3:
            return False, "連續 3 次止蝕，強制休息 24 小時"
        if self.today_trades >= 3:
            return False, "今日已交易 3 次，暫停"
        return True, "情緒正常"

    def reset_daily(self):
        self.today_trades = 0