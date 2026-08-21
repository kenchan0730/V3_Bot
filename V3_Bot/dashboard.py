"""Streamlit dashboard: live bot state, positions, P&L, and risk metrics."""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf

from core.config_loader import load_config
from core.data_utils import normalize_columns, quality_report
from core.market_breadth import MarketBreadth
from core.portfolio import Portfolio
from core.quant_engine import QuantEngine
from core.risk_manager import RiskManager
from core.strategies import MarketContext, load_strategies
from core.trading_state import TradingState


@st.cache_data(ttl=60)
def cached_config():
    try:
        return load_config("config.yaml", ".env")
    except Exception as exc:
        st.warning(f"設定載入失敗: {exc}")
        return {}


@st.cache_data(ttl=30)
def cached_history(symbol, period="3mo"):
    df = yf.download(symbol, period=period, interval="1d", progress=False)
    if df is None or df.empty:
        return None
    return normalize_columns(df)


@st.cache_data(ttl=60)
def cached_quote(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return float(data["Close"].iloc[-1]) if not data.empty else 0.0
    except Exception:
        return 0.0


@st.cache_data(ttl=30)
def cached_breadth():
    try:
        return MarketBreadth.get_breadth_score()
    except Exception:
        return {}


def load_state(config):
    path = Path(config.get("state", {}).get("file", "logs/state.json"))
    if not path.exists():
        return None, path
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except Exception:
        return None, path


def load_blotter(config, tail=25):
    path = Path(config.get("audit", {}).get("blotter_file", "logs/trade_blotter.csv"))
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        return df.tail(tail).iloc[::-1]
    except Exception:
        return None


def render():
    st.markdown("""
    <style>
        .stApp { background-color: #0E1117; color: #FFFFFF; }
    </style>
    """, unsafe_allow_html=True)

    config = cached_config()
    state_data, state_path = load_state(config)

    total_capital = float(config.get("capital", {}).get("total", 385.0) or 385.0)
    state = TradingState(initial_capital=total_capital, state_file=str(state_path))
    if state_data:
        state.total_capital = float(state_data.get("total_capital", total_capital))
        state.peak_capital = float(state_data.get("peak_capital", total_capital))
        state.daily_realized_pnl = float(state_data.get("daily_realized_pnl", 0.0))
        state.total_realized_pnl = float(state_data.get("total_realized_pnl", 0.0))
        state.consecutive_losses = int(state_data.get("consecutive_losses", 0))
        state.today_trades = int(state_data.get("today_trades", 0))
        state.halted = bool(state_data.get("halted", False))
        state.halt_reason = state_data.get("halt_reason", "")
        state.ledger = state_data.get("ledger", [])

    risk_mgr = RiskManager(initial_capital=total_capital, config=config.get("risk", {}), state=state)
    portfolio = Portfolio(config.get("portfolio", {}))

    st.markdown("<h2 style='text-align:center;'>📊 V4.5 交易儀表板</h2>", unsafe_allow_html=True)
    st.caption(f"更新時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ---- bot status ----
    if state_data is None:
        st.warning(f"尚未找到狀態檔 {state_path}（機器人可能未執行過）")
        bot_status = "❔ 未知"
    elif state.halted:
        bot_status = f"🔴 已停機：{state.halt_reason}"
    else:
        bot_status = f"🟢 運行中（最後保存 {state_data.get('saved_at', 'n/a')}）"

    spy_price = cached_quote("SPY")
    vix_price = cached_quote("^VIX")
    risk_mgr.check_vix(vix_price or 18.0)
    market_open = RiskManager.is_market_open()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("📈 SPY", f"${spy_price:.2f}" if spy_price else "N/A")
    col2.metric("📊 VIX", f"{vix_price:.1f}" if vix_price else "N/A")
    col3.metric("⏰ 市場", "🟢 開市中" if market_open else "🔴 已收市")
    col4.metric("🤖 機器人", bot_status.split("：")[0])
    if state.halted:
        st.error(f"風控停機：{state.halt_reason}")

    # ---- account & P&L ----
    st.markdown("---")
    st.markdown("#### 💰 帳戶與盈虧")
    ok_daily, daily_msg = risk_mgr.is_within_daily_loss_limit()
    ok_drawdown, drawdown_msg = risk_mgr.check_drawdown()
    drawdown_pct = 0.0
    if state.peak_capital > 0:
        drawdown_pct = (state.peak_capital - state.total_capital) / state.peak_capital * 100

    a, b, c, d = st.columns(4)
    a.metric("淨值", f"${state.total_capital:,.2f}")
    b.metric("當日已實現", f"${state.daily_realized_pnl:,.2f}", delta=daily_msg)
    c.metric("累計已實現", f"${state.total_realized_pnl:,.2f}")
    d.metric("回撤", f"{drawdown_pct:.2f}%", delta="OK" if ok_drawdown else drawdown_msg)

    e, f, g = st.columns(3)
    e.metric("單筆風險上限", f"${state.total_capital * risk_mgr.current_risk_pct / 100:,.2f}",
             delta=f"{risk_mgr.current_risk_pct}%")
    f.metric("連續止蝕", f"{state.consecutive_losses} 次")
    g.metric("今日交易", f"{state.today_trades} 筆")

    # ---- positions ----
    st.markdown("---")
    st.markdown("#### 📦 持倉與組合風險")
    positions = (state_data or {}).get("positions") or {}
    if positions:
        portfolio.sync(positions)
        st.dataframe(pd.DataFrame(portfolio.snapshot(state.total_capital)["positions"]).T,
                     use_container_width=True)
    else:
        st.info("狀態檔未包含持倉快照（IBKR 未連線或尚無持倉）。")

    snapshot = portfolio.snapshot(state.total_capital)
    p1, p2, p3 = st.columns(3)
    p1.metric("持倉數", f"{snapshot['open_positions']} / {snapshot['max_open_positions']}")
    p2.metric("總曝險", f"{snapshot['gross_exposure_pct']:.1f}%",
              delta=f"上限 {portfolio.max_gross_exposure_pct:.0f}%")
    p3.metric("未平倉風險", f"{snapshot['open_risk_pct']:.2f}%",
              delta=f"上限 {portfolio.max_total_open_risk_pct:.1f}%")

    # ---- live signal ----
    st.markdown("---")
    st.markdown("#### 📡 即時信號")
    watchlist = config.get("watchlist", ["AVAH"])
    symbol = st.selectbox("選擇標的", watchlist)

    df = cached_history(symbol)
    if df is None:
        st.warning(f"{symbol} 無法取得數據")
    else:
        report = quality_report(
            df,
            min_bars=int(config.get("data", {}).get("min_bars", 60)),
            max_age_trading_days=int(config.get("data", {}).get("max_age_trading_days", 2)),
        )
        if not report["ok"]:
            st.warning(f"數據品質警告 [{report['stage']}]: {report['message']}")

        price = float(df["close"].iloc[-1])
        quant = QuantEngine.dynamic_score(df)
        ma20 = float(df["close"].rolling(20).mean().iloc[-1])
        ma50 = float(df["close"].rolling(50).mean().iloc[-1])
        volume = float(df["volume"].iloc[-1])
        avg_volume = float(df["volume"].rolling(5).mean().iloc[-1])
        vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        zscore_min = float(config.get("zscore", {}).get("best_zone_min", 0.5))

        strategies = load_strategies(config)
        context = MarketContext(
            symbol=symbol, price=price, vix=vix_price or 18.0, zscore_min=zscore_min,
            quant=quant, vol_ratio=vol_ratio, ma20=ma20, ma50=ma50,
        )
        strategy = strategies[0]
        prefilter_ok, prefilter_reason = strategy.prefilter(df, context)
        signal = strategy.generate_signal(df, context) if prefilter_ok else {
            "action": "HOLD", "reason": prefilter_reason
        }

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("現價", f"${price:.2f}")
        s2.metric("Z-Score", f"{quant['z_score']:.2f}", delta=f"下限 {zscore_min}")
        s3.metric("RSI", f"{quant['rsi']:.1f}")
        s4.metric("量比", f"{vol_ratio:.2f}")

        badge = {"STRONG_BUY": "🟢 買入", "STRONG_SELL": "🔴 賣出"}.get(signal["action"], "🟡 觀察")
        st.write(f"**信號：** {badge} — {signal.get('reason', '')}")
        if signal["action"] == "STRONG_BUY":
            t1, t2, t3 = st.columns(3)
            t1.metric("入場", f"${signal['entry']:.2f}")
            t2.metric("止蝕", f"${signal['stop']:.2f}")
            t3.metric("目標1", f"${signal['target1']:.2f}")

        st.line_chart(df.set_index(df.index)["close"].tail(90))

    # ---- market breadth ----
    st.markdown("---")
    st.markdown("#### 🛡️ 市場寬度")
    breadth = cached_breadth()
    if breadth:
        score = breadth.get("score", 50)
        zone, zone_msg = MarketBreadth.get_health_zone(score)
        exposure = MarketBreadth.get_exposure_recommendation(score)
        b1, b2, b3 = st.columns(3)
        b1.metric("寬度分數", f"{score}/100", delta=zone)
        b2.metric("建議曝險", f"{exposure}%")
        b3.metric("狀態", zone_msg)

    # ---- blotter ----
    st.markdown("---")
    st.markdown("#### 🧾 稽核軌跡（最近 25 筆）")
    blotter = load_blotter(config)
    if blotter is not None and not blotter.empty:
        st.dataframe(blotter, use_container_width=True, height=320)
    else:
        st.info("尚無 blotter 記錄。")


render()
