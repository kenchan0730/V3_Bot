# app.py - V4.0 手機儀表板（Streamlit）
import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import plotly.graph_objects as go

# ----- 頁面設定 -----
st.set_page_config(page_title="V4.0 儀表板", page_icon="📊", layout="wide")

# ----- 自訂 CSS（手機優化）-----
st.markdown("""
<style>
    .stApp { background-color: #0E1117; color: #FFFFFF; }
    .card { background-color: #1E222D; border-radius: 15px; padding: 15px; margin-bottom: 10px; border: 1px solid #2A2F3A; }
    .metric-value { font-size: 24px; font-weight: bold; color: #00D4AA; }
    .metric-label { font-size: 12px; color: #8892A0; }
    .badge-green { background-color: #00D4AA; color: #0E1117; border-radius: 20px; padding: 2px 10px; font-size: 11px; font-weight: bold; }
    .badge-red { background-color: #FF4B4B; color: #0E1117; border-radius: 20px; padding: 2px 10px; font-size: 11px; font-weight: bold; }
    .badge-yellow { background-color: #FFB800; color: #0E1117; border-radius: 20px; padding: 2px 10px; font-size: 11px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ----- 標題 -----
st.markdown("<h2 style='text-align: center;'>📊 V4.0 交易儀表板</h2>", unsafe_allow_html=True)
st.caption(f"更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ----- 市場概覽 -----
try:
    spy = yf.Ticker("SPY")
    spy_data = spy.history(period="1d")
    spy_price = spy_data["Close"].iloc[-1] if not spy_data.empty else 0
    
    vix = yf.Ticker("^VIX")
    vix_data = vix.history(period="1d")
    vix_price = vix_data["Close"].iloc[-1] if not vix_data.empty else 0
except:
    spy_price = 0
    vix_price = 0

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("📈 SPY", f"${spy_price:.2f}" if spy_price else "N/A")
with col2:
    st.metric("📊 VIX", f"{vix_price:.1f}" if vix_price else "N/A")
with col3:
    # ----- 修正後的時間判斷（分段式）-----
    hour = datetime.now().hour
    is_open = (hour >= 21) or (hour < 4)
    status = "🟢 開市中" if is_open else "🔴 已收市"
    st.metric("⏰ 狀態", status)

# ----- 核心持倉（AVAH）-----
st.markdown("---")
st.markdown("#### 🎯 核心持倉：AVAH")

try:
    avah = yf.Ticker("AVAH")
    avah_data = avah.history(period="5d")
    avah_price = avah_data["Close"].iloc[-1] if not avah_data.empty else 0
    
    if not avah_data.empty and len(avah_data) >= 2:
        avah_change = ((avah_data["Close"].iloc[-1] - avah_data["Close"].iloc[-2]) / avah_data["Close"].iloc[-2]) * 100
    else:
        avah_change = 0
except:
    avah_price = 0
    avah_change = 0

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.metric("💰 現價", f"${avah_price:.2f}" if avah_price else "N/A", delta=f"{avah_change:.2f}%" if avah_price else None)
with col_b:
    st.metric("🎯 入場", "$12.20")
with col_c:
    st.metric("🛑 止蝕", "$11.70")

# ----- Z-Score 儀表（模擬）-----
st.markdown("---")
st.markdown("#### 📊 V4.0 技術信號")

z_score = 0.0  # 此處可串接你的 quant_engine
signal_color = "🟡"
signal_text = "等待"

if z_score >= 0.5:
    signal_color = "🟢"
    signal_text = "買入"
elif z_score < 0:
    signal_color = "🔴"
    signal_text = "觀望"

st.markdown(f"""
<div class="card">
    <div style="display: flex; justify-content: space-between;">
        <span>Z-Score</span>
        <span style="font-weight: bold;">{z_score:.2f}</span>
    </div>
    <div style="display: flex; justify-content: space-between;">
        <span>信號</span>
        <span>{signal_color} {signal_text}</span>
    </div>
    <div style="display: flex; justify-content: space-between;">
        <span>RSI（估計）</span>
        <span>~52</span>
    </div>
    <div style="display: flex; justify-content: space-between;">
        <span>量比</span>
        <span>0.85</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ----- 風險監控 -----
st.markdown("---")
st.markdown("#### 🛡️ 風險監控")

st.markdown("""
<div class="card">
    <div style="display: flex; justify-content: space-between;">
        <span>單筆風險上限</span>
        <span style="color: #00D4AA;">✅ $7.70</span>
    </div>
    <div style="display: flex; justify-content: space-between;">
        <span>當日浮虧</span>
        <span style="color: #FFB800;">⏳ -0.5%</span>
    </div>
    <div style="display: flex; justify-content: space-between;">
        <span>連續止蝕</span>
        <span>0 次</span>
    </div>
    <div style="display: flex; justify-content: space-between;">
        <span>市場寬度</span>
        <span>50/100（中性）</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ----- 底部導航 -----
st.markdown("""
<div style="position: fixed; bottom: 0; left: 0; width: 100%; background-color: #1E222D; border-top: 1px solid #2A2F3A; padding: 8px 0; text-align: center; color: #8892A0; font-size: 11px; z-index: 999;">
    <span style="margin: 0 10px;">🏠 首頁</span>
    <span style="margin: 0 10px;">📡 信號</span>
    <span style="margin: 0 10px;">🚨 警報</span>
    <span style="margin: 0 10px;">📚 記錄</span>
</div>
""", unsafe_allow_html=True)