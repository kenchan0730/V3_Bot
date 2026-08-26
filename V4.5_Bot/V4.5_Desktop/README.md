# V4.5 Desktop — Intelligence Application

桌面情報應用程式，整合 V4.5 全部分析能力，**不包含自動交易**。

## 功能模組

| 模組 | 說明 |
|------|------|
| 情報 | 實時美股新聞（約 2 分鐘輪詢）、1–10 情緒評分、自選股詳情（K 線、新聞、財報） |
| 技術面 | 市場環境 1–100、10 大 ETF、內部指標、11 板塊、頭條新聞、熱門基本面 |
| 內部交易 | 日曆選日、買賣統計、高確信、集體買入、綜合排名 |
| 日曆 | 財報日程、V4.5 評分與專業分析 |
| AI | V4.5 分析問答 + 購買訊號提醒 |
| 搜尋 | 美股/ETF 搜尋、熱門趨勢 20 條 |

## 快速啟動

```bash
cd V4.5_Bot

# 後端依賴（若尚未安裝）
pip install fastapi uvicorn

# 啟動 API（port 8765）
chmod +x V4.5_Desktop/start.sh
./V4.5_Desktop/start.sh

# 前端開發
cd V4.5_Desktop/frontend
npm install
npm run dev    # http://127.0.0.1:5173

# 或建置後由 API 靜態服務
npm run build
```

## 環境變數（可選）

- `FINNHUB_API_KEY` — 內部交易、財報日曆、搜尋（免費層）
- `TOTAL_CAPITAL` 等 — 沿用 `config.yaml` / `data/.env`

## 資料來源

- Yahoo Finance / Google News RSS（免費）
- Finnhub（可選）
- V4.5 `core/`：quant、regime、breadth、sector、fundamental、swing filters

## 注意

本應用為**純情報與分析**，不連接 IBKR 下單、不執行 `auto_trade`。
