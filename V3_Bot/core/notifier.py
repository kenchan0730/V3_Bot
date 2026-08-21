# core/notifier.py
import logging
import requests
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = self.config.get("enabled", False)
        self.telegram_token = self.config.get("telegram", {}).get("bot_token", "")
        self.telegram_chat_id = self.config.get("telegram", {}).get("chat_id", "")
        self.email_config = self.config.get("email", {})

    def send_telegram(self, message):
        """发送 Telegram 通知"""
        if not self.enabled or not self.telegram_token:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Telegram 发送失败: {e}")
            return False

    def send_email(self, subject, message):
        """发送 Email 通知"""
        if not self.enabled or not self.email_config.get("enabled"):
            return False

        try:
            smtp_server = self.email_config.get("smtp_server")
            username = self.email_config.get("username")
            password = self.email_config.get("password")
            recipient = self.email_config.get("recipient")

            msg = MIMEText(message)
            msg["Subject"] = subject
            msg["From"] = username
            msg["To"] = recipient

            with smtplib.SMTP(smtp_server, 587) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
            return True
        except Exception as e:
            logger.error(f"Email 发送失败: {e}")
            return False

    def send_trade_signal(self, symbol, action, price, stop_loss, target1, target2, shares):
        """发送交易信号通知"""
        message = f"""
📊 <b>V4.0 交易信号</b>

股票: {symbol}
操作: {action}
价格: ${price:.2f}
股数: {shares} 股
止损: ${stop_loss:.2f}
目标1: ${target1:.2f}
目标2: ${target2:.2f}
风险: ${(price - stop_loss) * shares:.2f}

时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}
"""
        return self.send_telegram(message)