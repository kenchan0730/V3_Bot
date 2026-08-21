#!/usr/bin/env python3
"""
V4.5 交易機器人 - 強化版
功能：K線自動識別 + 綜合信號 + 自動重連 + 時段過濾 + 日虧損上限
"""

import json
import logging
import signal
import sys
import time
import yaml
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path

from core.quant_engine import QuantEngine
from core.risk_manager import RiskManager
from core.emotion_manager import EmotionManager
from core.sector_tracker import SectorTracker
from core.market_breadth import MarketBreadth
from core.trading_signals import TradingSignals
from core.ibkr_connector import IBKRConnector
from core.data_utils import normalize_columns
from core.fundamental_filter import FundamentalFilter
from core.notifier import Notifier

STATE_FILE = Path("logs/state.json")
shutdown_requested = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/trading.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_vix():
    for attempt in range(3):
        try:
            vix = yf.Ticker("^VIX")
            data = vix.history(period="1d", progress=False)
            if not data.empty:
                return float(data["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"VIX 獲取失敗 (嘗試 {attempt + 1}/3): {e}")
            time.sleep(1)
    return 18.0


def fetch_symbol_data(symbol, ibkr):
    """Fetch OHLCV data from IBKR or yfinance fallback."""
    if ibkr.connected:
        df = ibkr.get_historical_data(symbol, duration="3 M", bar_size="1 day")
        if df is not None and len(df) >= 60:
            return df
        logger.warning(f"{symbol} IBKR 數據不足，改用 yfinance")
    df = yf.download(symbol, period="3mo", interval="1d", progress=False)
    if df.empty or len(df) < 60:
        return None
    return df


def save_state(risk_mgr, emotion):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "saved_at": datetime.now().isoformat(),
        "total_capital": risk_mgr.total_capital,
        "daily_loss": risk_mgr.daily_loss,
        "consecutive_losses": risk_mgr.consecutive_losses,
        "today_trades": risk_mgr.today_trades,
        "emotion_today_trades": emotion.today_trades,
        "emotion_consecutive_losses": emotion.consecutive_losses,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    logger.info(f"狀態已保存至 {STATE_FILE}")


def load_state(risk_mgr, emotion):
    if not STATE_FILE.exists():
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        risk_mgr.total_capital = float(state.get("total_capital", risk_mgr.total_capital))
        risk_mgr.daily_loss = float(state.get("daily_loss", 0.0))
        risk_mgr.consecutive_losses = int(state.get("consecutive_losses", 0))
        risk_mgr.today_trades = int(state.get("today_trades", 0))
        emotion.today_trades = int(state.get("emotion_today_trades", 0))
        emotion.consecutive_losses = int(state.get("emotion_consecutive_losses", 0))
        logger.info(f"已載入狀態 ({state.get('saved_at', 'unknown')})")
    except Exception as e:
        logger.warning(f"狀態載入失敗: {e}")


def request_shutdown(signum, frame):
    global shutdown_requested
    logger.info(f"收到停止信號 ({signum})，準備安全關閉...")
    shutdown_requested = True


def apply_sector_exposure(base_exposure, sector_enabled):
    if not sector_enabled:
        return base_exposure
    try:
        sector_info = SectorTracker.get_sector_rating()
        weights = sector_info.get("weights", {})
        if not weights:
            return base_exposure
        avg_weight = sum(weights.values()) / len(weights)
        adjusted = int(base_exposure * avg_weight / 100)
        for alert in sector_info.get("alerts", []):
            logger.warning(f"板塊警報: {alert}")
        return max(0, min(100, adjusted))
    except Exception as e:
        logger.warning(f"板塊分析失敗: {e}")
        return base_exposure


def main():
    global shutdown_requested

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    logger.info("=" * 60)
    logger.info("🚀 V4.5 交易機器人啟動 (強化版)")
    logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    config = load_config()
    risk_config = config.get("risk", {})
    total_capital = float(config.get("capital", {}).get("total", 385.0))
    auto_trade = config.get("trading", {}).get("auto_trade", False)
    market_hours_only = config.get("trading", {}).get("market_hours_only", True)
    price_limit = float(config.get("trading", {}).get("price_limit", 40))
    max_shares = int(config.get("trading", {}).get("max_shares", 20))
    sector_enabled = config.get("sector", {}).get("enabled", True)

    ibkr = IBKRConnector(
        config["ibkr"]["host"],
        config["ibkr"]["port"],
        config["ibkr"]["client_id"]
    )
    try:
        if not ibkr.connect():
            logger.warning("⚠️ IBKR 連線失敗，將使用 yfinance 數據（僅顯示信號）")
        else:
            logger.info("✅ IBKR 已連線")
    except Exception as e:
        logger.error(f"IBKR 初始化失敗: {e}")

    risk_mgr = RiskManager(
        total_capital,
        risk_config.get("max_risk_percent", 2.0),
        risk_config.get("daily_loss_limit", 2.0),
    )
    emotion = EmotionManager()
    fundamental = FundamentalFilter(config.get("fundamental", {}))
    notifier = Notifier(config.get("notifier", {}))
    load_state(risk_mgr, emotion)

    try:
        vix = get_vix()
        risk_mgr.check_vix(vix)
    except Exception as e:
        logger.error(f"VIX 檢查失敗: {e}")
        vix = 18.0

    breadth = MarketBreadth.get_breadth_score()
    if breadth:
        score = breadth["score"]
        zone, zone_msg = MarketBreadth.get_health_zone(score)
        exposure = MarketBreadth.get_exposure_recommendation(score)
        logger.info(f"📊 市場寬度: {score}/100 ({zone}) — {zone_msg}")
        if score < 20:
            logger.error("🔴 市場寬度危急，暫停交易")
            save_state(risk_mgr, emotion)
            ibkr.disconnect()
            return
        zscore_min = 0.8 if score < 40 else config.get("zscore", {}).get("best_zone_min", 0.5)
    else:
        zscore_min = config.get("zscore", {}).get("best_zone_min", 0.5)
        exposure = 100

    exposure = apply_sector_exposure(exposure, sector_enabled)
    logger.info(f"📉 建議曝險: {exposure}% | Z-Score 下限: {zscore_min}")

    watchlist = config.get("watchlist", ["AVAH"])
    cycle = 0

    try:
        while not shutdown_requested:
            cycle += 1
            logger.info(f"\n🔄 第 {cycle} 次掃描 ({datetime.now().strftime('%H:%M:%S')})")

            if market_hours_only and not RiskManager.is_market_open():
                logger.info("💤 美股已收市，暫停掃描 10 分鐘")
                for _ in range(60):
                    if shutdown_requested:
                        break
                    time.sleep(10)
                continue

            ok_drawdown, drawdown_msg = risk_mgr.check_drawdown()
            if not ok_drawdown:
                logger.error(f"🔴 回撤限制: {drawdown_msg}")
                break

            ok_daily, daily_msg = risk_mgr.is_within_daily_loss_limit()
            if not ok_daily:
                logger.error(f"🔴 {daily_msg}")
                break
            logger.info(f"💰 當日 P&L: ${risk_mgr.get_daily_pnl():.2f} ({daily_msg})")

            try:
                vix = get_vix()
                risk_mgr.check_vix(vix)
            except Exception as e:
                logger.warning(f"VIX 更新失敗: {e}")

            for symbol in watchlist:
                if shutdown_requested:
                    break
                logger.info(f"\n🔍 分析: {symbol}")

                try:
                    passed, fund_reason = fundamental.filter(symbol)
                    if not passed:
                        logger.info(f"   ⏳ 基本面過濾: {fund_reason}")
                        continue

                    raw_df = fetch_symbol_data(symbol, ibkr)
                    if raw_df is None:
                        logger.warning(f"{symbol} 數據不足")
                        continue

                    df = normalize_columns(raw_df)
                    price = float(df["close"].iloc[-1])

                    if price <= 0 or price > price_limit:
                        logger.info(f"股價 ${price:.2f} 超出上限，跳過")
                        continue

                    quant = QuantEngine.dynamic_score(df)
                    z_score = quant["z_score"]
                    rsi = quant["rsi"]

                    if z_score < zscore_min:
                        logger.info(f"   ⏳ Z-Score {z_score:.2f} < 下限 {zscore_min}")
                        continue

                    ma20_val = float(df["close"].rolling(20).mean().iloc[-1])
                    ma50_val = float(df["close"].rolling(50).mean().iloc[-1])
                    if pd.isna(ma20_val) or pd.isna(ma50_val):
                        continue
                    if not (price > ma20_val > ma50_val):
                        logger.info(f"   ⏳ 結構過濾失敗 (price>{ma20_val:.2f}>{ma50_val:.2f})")
                        continue

                    vol = float(df["volume"].iloc[-1])
                    avg_vol = float(df["volume"].rolling(5).mean().iloc[-1])
                    vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0
                    if not (vol_ratio > 1.5 or vol_ratio < 0.8):
                        logger.info(f"   ⏳ 量比 {vol_ratio:.2f} 不符合")
                        continue

                    can_trade_emotion, emo_msg = emotion.check_before_trade()
                    if not can_trade_emotion:
                        logger.warning(f"   {emo_msg}")
                        continue

                    signal = TradingSignals.get_combined_signal(
                        df, price, vix, z_score, vol_ratio, ma20_val, ma50_val,
                        zscore_min=zscore_min,
                    )

                    if signal["action"] == "STRONG_BUY":
                        shares = risk_mgr.calculate_position_size(
                            signal["entry"], signal["stop"], price_limit, max_shares
                        )
                        if exposure < 100:
                            shares = int(shares * exposure / 100)
                        if shares <= 0:
                            logger.info("   ⏳ 曝險調整後股數為 0，跳過")
                            continue

                        cost = shares * signal["entry"]
                        logger.info("   🎯 買入信號觸發！")
                        logger.info(f"   📊 買入 {shares} 股 @ ${signal['entry']:.2f}")
                        logger.info(f"   🛑 止蝕: ${signal['stop']:.2f}")
                        logger.info(f"   🎯 目標1: ${signal['target1']:.2f} | 目標2: ${signal['target2']:.2f}")
                        logger.info(f"   💰 成本: ${cost:.2f} (佔 {cost / risk_mgr.total_capital * 100:.1f}%)")
                        logger.info(f"   ⚠️ 風險: ${(signal['entry'] - signal['stop']) * shares:.2f}")
                        logger.info(f"   📝 原因: {signal['reason']}")

                        notifier.send_trade_signal(
                            symbol, "BUY", signal["entry"], signal["stop"],
                            signal["target1"], signal["target2"], shares
                        )

                        if auto_trade:
                            try:
                                ibkr.place_order_with_retry(
                                    symbol, "BUY", shares, limit_price=signal["entry"]
                                )
                                emotion.record_trade(0)
                                risk_mgr.today_trades += 1
                            except Exception as e:
                                logger.error(f"下單失敗 {symbol}: {e}")

                    elif signal["action"] == "STRONG_SELL":
                        logger.info(f"   🔴 賣出信號觸發: {signal['reason']}")
                        notifier.send_trade_signal(
                            symbol, "SELL", price, price * 0.98, price * 1.02, price * 1.04, 0
                        )
                        if auto_trade:
                            logger.info("   自動平倉尚未實作")
                    else:
                        logger.info(f"   ⏳ {signal['reason']} (RSI {rsi:.1f})")

                except Exception as e:
                    logger.exception(f"分析 {symbol} 時發生錯誤: {e}")

            if shutdown_requested:
                break

            for _ in range(30):
                if shutdown_requested:
                    break
                time.sleep(10)

    except Exception as e:
        logger.exception(f"主循環異常: {e}")
    finally:
        save_state(risk_mgr, emotion)
        try:
            ibkr.disconnect()
        except Exception as e:
            logger.warning(f"IBKR 斷線時發生錯誤: {e}")
        logger.info("👋 V4.5 交易機器人已安全關閉")


if __name__ == "__main__":
    main()
