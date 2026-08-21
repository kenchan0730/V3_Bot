# app.py - V4.5 手機儀表板（Streamlit）
import streamlit as st
import yfinance as yf
import yaml
from datetime import datetime

from core.quant_engine import QuantEngine
from core.market_breadth import MarketBreadth
from core.risk_manager import RiskManager
from core.trading_signals import TradingSignals
from core.data_utils import normalize_columns

WATCH_SYMBOL = "AVAH"


def load_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def fetch_history(symbol, period="3mo"):
    df = yf.download(symbol, period=period, interval="1d", progress=False)
    if df.empty or len(df) < 60:
        return None
    return normalize_columns(df)


st.set_page_config(page_title="V4.5 儀表板", page_icon="📊", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: #FFFFFF; }
    .card { background-color: #1E222D; border-radius: 15px; padding: 15px; margin-bottom: 10px; border: 1px solid #2A2F3A; }
</style>
""", unsafe_allow_html=True)

config = load_config()
total_capital = float(config.get("capital", {}).get("total", 385.0))
risk_config = config.get("risk", {})
risk_mgr = RiskManager(
    total_capital,
    risk_config.get("max_risk_percent", 2.0),
    risk_config.get("daily_loss_limit", 2.0),
)

st.markdown("<h2 style='text-align: center;'>📊 V4.5 交易儀表板</h2>", unsafe_allow_html=True)
st.caption(f"更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

spy_price = 0.0
vix_price = 0.0
try:
    spy_data = yf.Ticker("SPY").history(period="1d")
    spy_price = float(spy_data["Close"].iloc[-1]) if not spy_data.empty else 0.0
    vix_data = yf.Ticker("^VIX").history(period="1d")
    vix_price = float(vix_data["Close"].iloc[-1]) if not vix_data.empty else 0.0
except Exception as e:
    st.warning(f"市場數據獲取失敗: {e}")

risk_mgr.check_vix(vix_price if vix_price else 18.0)
market_open = RiskManager.is_market_open()
status = "🟢 開市中" if market_open else "🔴 已收市"

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("📈 SPY", f"${spy_price:.2f}" if spy_price else "N/A")
with col2:
    st.metric("📊 VIX", f"{vix_price:.1f}" if vix_price else "N/A")
with col3:
    st.metric("⏰ 狀態", status)

st.markdown("---")
st.markdown(f"#### 🎯 核心持倉：{WATCH_SYMBOL}")

avah_price = 0.0
avah_change = 0.0
z_score = 0.0
rsi = 50.0
vol_ratio = 0.0
signal_text = "等待"
signal_color = "🟡"
signal_detail = "數據不足"
signal = {}

df = fetch_history(WATCH_SYMBOL)
if df is not None:
    avah_price = float(df["close"].iloc[-1])
    if len(df) >= 2:
        prev = float(df["close"].iloc[-2])
        avah_change = ((avah_price - prev) / prev) * 100 if prev else 0.0

    quant = QuantEngine.dynamic_score(df)
    z_score = quant["z_score"]
    rsi = quant["rsi"]

    vol = float(df["volume"].iloc[-1])
    avg_vol = float(df["volume"].rolling(5).mean().iloc[-1])
    vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0

    ma20 = float(df["close"].rolling(20).mean().iloc[-1])
    ma50 = float(df["close"].rolling(50).mean().iloc[-1])
    zscore_min = config.get("zscore", {}).get("best_zone_min", 0.5)
    signal = TradingSignals.get_combined_signal(
        df, avah_price, vix_price or 18.0, z_score, vol_ratio, ma20, ma50, zscore_min=zscore_min
    )
    signal_detail = signal.get("reason", "")
    if signal["action"] == "STRONG_BUY":
        signal_color, signal_text = "🟢", "買入"
    elif signal["action"] == "STRONG_SELL":
        signal_color, signal_text = "🔴", "賣出"
    elif z_score >= zscore_min:
        signal_color, signal_text = "🟡", "觀察"
    else:
        signal_color, signal_text = "🔴", "觀望"

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.metric("💰 現價", f"${avah_price:.2f}" if avah_price else "N/A", delta=f"{avah_change:.2f}%" if avah_price else None)
with col_b:
    entry = signal.get("entry", avah_price) if df is not None and isinstance(signal, dict) else avah_price
    st.metric("🎯 入場", f"${entry:.2f}" if entry else "N/A")
with col_c:
    stop = signal.get("stop", avah_price * 0.98) if df is not None and isinstance(signal, dict) else None
    st.metric("🛑 止蝕", f"${stop:.2f}" if stop else "N/A")

st.markdown("---")
st.markdown("#### 📊 V4.5 技術信號")
st.markdown(f"""
<div class="card">
    <div style="display: flex; justify-content: space-between;"><span>Z-Score</span><span style="font-weight: bold;">{z_score:.2f}</span></div>
    <div style="display: flex; justify-content: space-between;"><span>信號</span><span>{signal_color} {signal_text}</span></div>
    <div style="display: flex; justify-content: space-between;"><span>RSI</span><span>{rsi:.1f}</span></div>
    <div style="display: flex; justify-content: space-between;"><span>量比</span><span>{vol_ratio:.2f}</span></div>
    <div style="display: flex; justify-content: space-between;"><span>說明</span><span>{signal_detail}</span></div>
</div>
""", unsafe_allow_html=True)

st.markdown("---")
st.markdown("#### 🛡️ 風險監控")

breadth = MarketBreadth.get_breadth_score()
breadth_score = breadth.get("score", 50)
breadth_zone = breadth.get("zone", "NEUTRAL")
ok_drawdown, drawdown_msg = risk_mgr.check_drawdown()
ok_daily, daily_msg = risk_mgr.is_within_daily_loss_limit()
max_risk_usd = risk_mgr.total_capital * (risk_mgr.current_risk_pct / 100.0)

st.markdown(f"""
<div class="card">
    <div style="display: flex; justify-content: space-between;"><span>單筆風險上限</span><span style="color: #00D4AA;">${max_risk_usd:.2f} ({risk_mgr.current_risk_pct}%)</span></div>
    <div style="display: flex; justify-content: space-between;"><span>當日 P&L</span><span>${risk_mgr.get_daily_pnl():.2f} ({daily_msg})</span></div>
    <div style="display: flex; justify-content: space-between;"><span>連續止蝕</span><span>{risk_mgr.consecutive_losses} 次</span></div>
    <div style="display: flex; justify-content: space-between;"><span>回撤檢查</span><span>{'✅' if ok_drawdown else '🔴'} {drawdown_msg}</span></div>
    <div style="display: flex; justify-content: space-between;"><span>市場寬度</span><span>{breadth_score}/100（{breadth_zone}）</span></div>
</div>
""", unsafe_allow_html=True)
