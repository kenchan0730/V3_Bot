"""Operator alerting over Telegram/email with per-key throttling."""

import logging
import smtplib
import time
import traceback
from email.mime.text import MIMEText

import requests

logger = logging.getLogger(__name__)

CRITICAL = "CRITICAL"
WARNING = "WARNING"
INFO = "INFO"

ICONS = {CRITICAL: "🔴", WARNING: "⚠️", INFO: "ℹ️"}


class Notifier:
    def __init__(self, config=None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))
        telegram = self.config.get("telegram", {}) or {}
        self.telegram_token = telegram.get("bot_token", "") or ""
        self.telegram_chat_id = telegram.get("chat_id", "") or ""
        self.email_config = self.config.get("email", {}) or {}
        self.throttle_seconds = int(self.config.get("throttle_seconds", 300))
        self._last_sent = {}

    # ----- transport -----

    def send_telegram(self, message):
        if not self.enabled or not self.telegram_token or not self.telegram_chat_id:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {"chat_id": self.telegram_chat_id, "text": message, "parse_mode": "HTML"}
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code != 200:
                logger.error(f"Telegram 回應 {response.status_code}: {response.text[:200]}")
                return False
            return True
        except Exception as e:
            logger.error(f"Telegram 發送失敗: {e}")
            return False

    def send_email(self, subject, message):
        if not self.enabled or not self.email_config.get("enabled"):
            return False
        try:
            msg = MIMEText(message)
            msg["Subject"] = subject
            msg["From"] = self.email_config.get("username", "")
            msg["To"] = self.email_config.get("recipient", "")
            with smtplib.SMTP(self.email_config.get("smtp_server"), int(self.email_config.get("port", 587))) as server:
                server.starttls()
                server.login(self.email_config.get("username"), self.email_config.get("password"))
                server.send_message(msg)
            return True
        except Exception as e:
            logger.error(f"Email 發送失敗: {e}")
            return False

    # ----- alert core -----

    def _throttled(self, key):
        if not key:
            return False
        now = time.time()
        last = self._last_sent.get(key, 0)
        if now - last < self.throttle_seconds:
            return True
        self._last_sent[key] = now
        return False

    def alert(self, level, title, message, key=None, force=False):
        """Send an operator alert. Repeat alerts with the same key are throttled."""
        log_line = f"[{level}] {title}: {message}"
        if level == CRITICAL:
            logger.error(log_line)
        elif level == WARNING:
            logger.warning(log_line)
        else:
            logger.info(log_line)

        if not force and self._throttled(key or title):
            return False

        body = f"{ICONS.get(level, '')} <b>{title}</b>\n\n{message}"
        sent = self.send_telegram(body)
        if level == CRITICAL:
            self.send_email(f"[V4.5 {level}] {title}", f"{title}\n\n{message}")
        return sent

    # ----- specific alerts (H9) -----

    def alert_disconnect(self, detail="IBKR 連線中斷"):
        return self.alert(CRITICAL, "IBKR 連線中斷", detail, key="ibkr_disconnect")

    def alert_data_failure(self, symbol, attempts, detail=""):
        return self.alert(
            WARNING, "數據獲取重複失敗",
            f"{symbol} 連續 {attempts} 次失敗。{detail}",
            key=f"data_fail_{symbol}",
        )

    def alert_stale_data(self, symbol, message):
        return self.alert(WARNING, "數據過期", f"{symbol}: {message}", key=f"stale_{symbol}")

    def alert_daily_loss(self, message):
        return self.alert(CRITICAL, "每日虧損上限觸發", message, key="daily_loss", force=True)

    def alert_risk_limit(self, message):
        return self.alert(CRITICAL, "風險限額觸發", message, key="risk_limit", force=True)

    def alert_exception(self, context, exc):
        detail = f"{context}\n\n{type(exc).__name__}: {exc}\n\n{traceback.format_exc()[:1500]}"
        return self.alert(CRITICAL, "未處理異常", detail, key=f"exc_{context}")

    def alert_order_issue(self, symbol, message):
        return self.alert(CRITICAL, "訂單異常", f"{symbol}: {message}", key=f"order_{symbol}")

    def alert_startup(self, message):
        return self.alert(INFO, "系統啟動", message, key="startup", force=True)

    def alert_shutdown(self, message):
        return self.alert(INFO, "系統關閉", message, key="shutdown", force=True)

    # ----- trade notifications -----

    def send_trade_signal(self, symbol, action, price, stop_loss, target1, target2, shares):
        message = (
            f"📊 <b>V4.5 交易信號</b>\n\n"
            f"股票: {symbol}\n"
            f"操作: {action}\n"
            f"價格: ${price:.2f}\n"
            f"股數: {shares}\n"
            f"止損: ${stop_loss:.2f}\n"
            f"目標1: ${target1:.2f}\n"
            f"目標2: ${target2:.2f}\n"
            f"風險: ${(price - stop_loss) * shares:.2f}\n"
            f"時間: {time.strftime('%Y-%m-%d %H:%M')}"
        )
        return self.send_telegram(message)
