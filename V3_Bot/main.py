#!/usr/bin/env python3
"""
V4.5 交易機器人 - 強化版
功能：K線自動識別 + 綜合信號 + 自動重連 + 時段過濾 + 日虧損上限
"""

import yaml
import logging
import time
import yfinance as yf
import pandas as pd
from datetime import datetime
import pytz
from core.quant_engine import QuantEngine
from core.risk_manager import RiskManager
from core.emotion_manager import EmotionManager
from core.sector_tracker import SectorTracker
from core.market_breadth import MarketBreadth
from core.candle_patterns import CandlePatterns
from core.trading_signals import TradingSignals
from core.ibkr_connector import IBKRConnector  # 若不用 IBKR 可註解
from core.data_utils import normalize_columns

# 日誌設定
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
    for _ in range(3):
        try:
            vix = yf.Ticker("^VIX")
            data = vix.history(period="1d", progress=False)
            if not data.empty:
                return float(data["Close"].iloc[-1])
        except:
            time.sleep(1)
    return 18.0

def is_market_open():
    """檢查目前是否為美股普通交易時段（美東 9:30 - 16:00）"""
    et = pytz.timezone("US/Eastern")
    now = datetime.now(et)
    is_weekday = now.weekday() < 5
    is_trading_hour = (9, 30) <= (now.hour, now.minute) < (16, 0)
    return is_weekday and is_trading_hour

def get_daily_pnl():
    """模擬獲取當日盈虧（實際需串接 IBKR 持倉）"""
    # 此處可改成從 IBKR 或自定義變數讀取
    return 0.0

def check_daily_loss_limit(total_capital, daily_pnl):
    if total_capital <= 0:
        return True
    loss_pct = (daily_pnl / total_capital) * 100
    if loss_pct < -2.0:
        logger.error(f"🔴 今日虧損已達 {loss_pct:.2f}%，強制停機")
        return False
    return True

def get_close_col(df):
    return 'close' if 'close' in df.columns else 'Close'
def get_high_col(df):
    return 'high' if 'high' in df.columns else 'High'
def get_low_col(df):
    return 'low' if 'low' in df.columns else 'Low'
def get_volume_col(df):
    return 'volume' if 'volume' in df.columns else 'Volume'

def main():
    logger.info("=" * 60)
    logger.info("🚀 V4.5 交易機器人啟動 (強化版)")
    logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    config = load_config()
    total_capital = float(config.get("capital", {}).get("total", 385.0))
    auto_trade = config.get("trading", {}).get("auto_trade", False)
    market_hours_only = config.get("trading", {}).get("market_hours_only", True)
    price_limit = float(config.get("trading", {}).get("price_limit", 40))
    max_shares = int(config.get("trading", {}).get("max_shares", 20))

    # 初始化 IBKR 連接器（若不使用可註解）
    ibkr = IBKRConnector(
        config["ibkr"]["host"],
        config["ibkr"]["port"],
        config["ibkr"]["client_id"]
    )
    if not ibkr.connect():
        logger.warning("⚠️ IBKR 連線失敗，將使用 yfinance 數據（僅顯示信號）")
    else:
        logger.info("✅ IBKR 已連線")

    risk_mgr = RiskManager(total_capital, config["risk"]["max_risk_percent"])
    emotion = EmotionManager()
    vix = get_vix()
    risk_mgr.check_vix(vix)

    # 市場寬度
    breadth = MarketBreadth.get_breadth_score()
    if breadth:
        score = breadth["score"]
        zone, _ = MarketBreadth.get_health_zone(score)
        exposure = MarketBreadth.get_exposure_recommendation(score)
        logger.info(f"📊 市場寬度: {score}/100 ({zone})")
        if score < 20:
            logger.error("🔴 市場寬度危急，暫停交易")
            return
        if score < 40:
            ZSCORE_MIN = 0.8
        else:
            ZSCORE_MIN = 0.5
    else:
        ZSCORE_MIN = 0.5
        exposure = 100

    watchlist = config.get("watchlist", ["AVAH"])
    daily_pnl = 0.0

    cycle = 0
    while True:
        cycle += 1
        logger.info(f"\n🔄 第 {cycle} 次掃描 ({datetime.now().strftime('%H:%M:%S')})")

        # 時段過濾
        if market_hours_only and not is_market_open():
            logger.info("💤 美股已收市，暫停掃描 10 分鐘")
            time.sleep(600)
            continue

        # 日虧損檢查
        if not check_daily_loss_limit(total_capital, daily_pnl):
            break

        vix = get_vix()
        risk_mgr.check_vix(vix)

        for symbol in watchlist:
            logger.info(f"\n🔍 分析: {symbol}")

            # 獲取數據（優先使用 IBKR，備援 yfinance）
            try:
                if ibkr.connected:
                    df = ibkr.get_historical_data(symbol, duration="3 M", bar_size="1 day")
                    if df is None or len(df) < 60:
                        raise Exception("IBKR 數據不足")
                else:
                    raise Exception("IBKR 未連線")
            except:
                # 備援 yfinance
                df = yf.download(symbol, period="3mo", interval="1d", progress=False)
                if df.empty or len(df) < 60:
                    logger.warning(f"{symbol} 數據不足")
                    continue

            df = normalize_columns(df)

            close_col = get_close_col(df)
            high_col = get_high_col(df)
            low_col = get_low_col(df)
            volume_col = get_volume_col(df)

            price = float(df[close_col].iloc[-1])

            if price <= 0 or price > price_limit:
                logger.info(f"股價 ${price:.2f} 超出上限，跳過")
                continue

            # V4.0 量化
            quant = QuantEngine.dynamic_score(df)
            z_score = quant["z_score"]
            rsi = quant["rsi"]

            # 市場結構
            ma20_val = float(df[close_col].rolling(20).mean().iloc[-1])
            ma50_val = float(df[close_col].rolling(50).mean().iloc[-1])
            if pd.isna(ma20_val) or pd.isna(ma50_val):
                continue
            if not (price > ma20_val > ma50_val):
                logger.info(f"   ⏳ 結構過濾失敗 (price>{ma20_val:.2f}>{ma50_val:.2f})")
                continue

            # 量比
            vol = float(df[volume_col].iloc[-1])
            avg_vol = float(df[volume_col].rolling(5).mean().iloc[-1])
            vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0
            if not (vol_ratio > 1.5 or vol_ratio < 0.8):
                logger.info(f"   ⏳ 量比 {vol_ratio:.2f} 不符合")
                continue

            # 情緒
            can_trade_emotion, emo_msg = emotion.check_before_trade()
            if not can_trade_emotion:
                logger.warning(f"   {emo_msg}")
                continue

            # K線 + 綜合信號
            signal = TradingSignals.get_combined_signal(
                df, price, vix, z_score, vol_ratio, ma20_val, ma50_val
            )

            if signal["action"] == "STRONG_BUY":
                # 計算股數
                risk_amt = total_capital * 0.02
                risk_per_share = signal["entry"] - signal["stop"]
                if risk_per_share <= 0:
                    continue
                shares = int(risk_amt / risk_per_share)
                shares = min(shares, max_shares)
                if shares <= 0:
                    continue

                # 檢查倉位集中度
                cost = shares * signal["entry"]
                if cost > total_capital * 0.5:
                    shares = int((total_capital * 0.5) / signal["entry"])
                if shares <= 0:
                    continue

                logger.info(f"   🎯 買入信號觸發！")
                logger.info(f"   📊 買入 {shares} 股 @ ${signal['entry']:.2f}")
                logger.info(f"   🛑 止蝕: ${signal['stop']:.2f}")
                logger.info(f"   🎯 目標1: ${signal['target1']:.2f} | 目標2: ${signal['target2']:.2f}")
                logger.info(f"   💰 成本: ${cost:.2f} (佔 {cost/total_capital*100:.1f}%)")
                logger.info(f"   ⚠️ 風險: ${(signal['entry']-signal['stop'])*shares:.2f}")
                logger.info(f"   📝 原因: {signal['reason']}")

                if auto_trade:
                    # 自動下單（需實作下單函數）
                    ibkr.place_order_with_retry(symbol, 'BUY', shares, limit_price=signal['entry'])

            elif signal["action"] == "STRONG_SELL":
                logger.info(f"   🔴 賣出信號觸發: {signal['reason']}")
                if auto_trade:
                    # 平倉所有持倉
                    pass
            else:
                logger.info(f"   ⏳ {signal['reason']}")

        time.sleep(300)  # 5分鐘掃描一次

if __name__ == "__main__":
    main()