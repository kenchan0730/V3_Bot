import streamlit as st

st.title("ℹ️ 關於")

st.markdown("""
### V4.5 交易系統（機構級）

美股量化交易平台，包含量化評分、K 線形態、市場寬度過濾，以及可選的
Interactive Brokers 自動執行。

**核心模組**

| 模組 | 功能 |
|------|------|
| `quant_engine` | Z-Score、RSI、動能／量能／波動評分 |
| `candle_patterns` | K 線形態識別 |
| `trading_signals` | 綜合信號判斷 |
| `risk_manager` | 倉位計算、VIX、回撤、每日虧損 |
| `portfolio` | 組合曝險、板塊集中度、相關性 |
| `order_manager` | 訂單生命週期、部分成交、逾時取消 |
| `blotter` | 稽核軌跡（append-only CSV） |
| `ibkr_connector` | IBKR 行情、Bracket 訂單、對帳 |

**安全設計**

- 每筆進場皆以 Bracket 訂單送出，停損由券商端保管。
- `auto_trade` 預設關閉；Bracket 下單失敗即放棄進場，不留無保護持倉。
- 風控觸發後系統停機並發出告警。
""")
