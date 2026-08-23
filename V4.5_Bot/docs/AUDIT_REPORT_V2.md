# V4.5 交易系統 — AI 深度審計報告

> **狀態：已回應。** 本報告的 🔴 全部項目，以及 🟡/🟢 除 `EntryPipeline` 重構外的所有項目均已修正。
> 逐項對照見 [AUDIT_RESPONSE.md](AUDIT_RESPONSE.md)。以下保留審計原文作為基準紀錄。

> 審計對象：`kenchan0730/V3_Bot` @ `cursor/v45-institutional-upgrade-16b9`（`V4.5_Bot/`）
> 審計方式：**逐檔閱讀原始碼**（main.py、core/ 全部 34 個模組、backtest/、tests/、Dockerfile、CI），非憑描述推測。
> 帳戶規模：約 **$1,275**（注意：`.env.example` 預設 `TOTAL_CAPITAL=385.0`，需確認 `.env` 已更新，見 🔴 P0）

---

## 📊 執行摘要

**整體評分：6.5 / 10**（架構企圖心 9/10，但有一個會讓「策略邏輯」完全失效的整合層 Bug，把實際可用性拉低）

這是一個工程上相當扎實的系統：分層清楚（風控 / 組合 / 執行 / 心態層獨立成模組）、347 個單元測試、CI 有 75% 覆蓋率門檻、Bracket 訂單拒絕無停損下單、狀態持久化用原子寫入。**但我在交叉比對 `trading_signals.py` 的輸出格式與 `professional_mind.py` 的消費邏輯時，發現一個 100% 可重現、會讓每一個真實買入信號在下單前被吃掉例外並默默跳過的型別錯誤**——這不是理論風險，是會直接讓 `auto_trade=true` 形同虛設的程式碼路徑。

### ✅ 最關鍵的 3 個優勢
1. **風控是多層真實聯動的，不是裝飾**：`RiskManager` → `Portfolio.can_open()` → `ProfessionalMind.approve_entry()` → `validate_pre_trade()` 四層都會否決下單，且都寫入 blotter，稽核軌跡完整。
2. **Bracket 訂單設計正確**：`ibkr_connector.place_bracket_order()` 明確拒絕 `stop_price<=0` 的請求（`"拒絕無停損的訂單"`），且優先用 `ib_insync.bracketOrder()` 原生 OCA，失敗才手動組裝 parent/TP/SL 三腳 — 這保證停損單留在券商端，機器人斷線也有保護。
3. **回測引擎確實重用了部分實戰程式碼**（`QuantEngine`、策略插件、`RiskManager`、`Portfolio`），不是兩套邏輯各寫各的 —— 但重用範圍不完整（見 §6）。

### ⚠️ 最關鍵的 3 個劣勢
1. **🔴 致命 Bug：`confidence="HIGH"` 傳入 `float()` 會拋例外，導致每個真實 STRONG_BUY 信號在 `ProfessionalMind` 評分階段被吞掉**（詳見 §4 / §6）。這是本次審計最重要的單一發現。
2. **`OrderManager` 只追蹤 Bracket 的 parent（entry）腳，完全不追蹤 stop-loss / take-profit 兩個子單的狀態** —— 你提示詞裡自己點名的「止蝕單未被券商接收」風險，程式碼層面目前沒有任何偵測機制。
3. **倉位集中度上限（50%）與板塊/總曝險上限（40% / 100%）遠寬於 J Law 標準（15–20% / 60%）**，且 regime 偵測出的曝險建議只是「軟性乘上股數」，不是硬性覆蓋 `Portfolio` 的曝險上限 —— 在 RISK_ON 時系統可以合法讓單一持倉逼近帳戶一半。

---

## 🏛️ 架構審計

**耦合度**：`main.py`（758 行）扮演編排器，直接 `import` 並實例化全部 20+ 模組——這是集中式組裝（composition root），不是嚴格意義的「上帝物件」，因為每個模組各自封裝了自己的邏輯（`RiskManager` 不知道 `Portfolio` 的存在，兩者透過 `main.py` 傳參協調）。這是可接受的權衡：對一個單體交易機器人而言，過度抽象（例如引入事件匯流排）在目前規模下反而增加除錯難度。

**循環依賴**：未發現。`core/` 內模組呈樹狀依賴（`professional_mind.py` 依賴 6 個子模組，但那 6 個子模組互不依賴），`strategies/` 透過 `BaseStrategy` 契約解耦，符合插件化設計。

**該拆的地方**：
- `main.py` 的 `handle_buy()`（第 345–436 行）一個函式做了「滑點調整 → 盤中確認 → 倉位計算 → 相關性縮放 → 心態層審批 → 停損覆蓋 → 下單前驗證 → 送單 → 記錄」9 個階段，長達 90 行且職責過多。建議拆成 `EntryPipeline` 類別，每階段是一個可獨立測試的步驟（目前這條路徑的整合層 Bug 沒被抓到，很大程度跟這個函式太長、沒有分階段單元測試有關）。
- `config.yaml` 裡 `risk.max_position_pct`（50.0）與 `portfolio.max_symbol_pct`（50.0）是兩個不同模組（`RiskManager.calculate_position_size` 和 `Portfolio.can_open`）各自讀取的同名概念，數值恰好相等但**沒有單一事實來源**，未來改一個忘記改另一個會產生不一致的風控上限。

---

## 🛡️ 風險管理審計

**對比 J Law 標準**（單筆風險 1–1.5%、單一持倉 ≤15–20%、總倉位 ≤60%）：

| 項目 | 系統目前設定 | J Law 標準 | 差距 |
|---|---|---|---|
| 單筆風險 | `max_risk_percent: 2.0` | 1–1.5% | 略寬，且連續 3 敗後降至 `reduced_risk_percent: 1.0`（機制良好） |
| 單一持倉集中度 | `max_position_pct` / `max_symbol_pct`: **50.0%** | 15–20% | **差距達 2.5–3.3 倍**，$1,275 帳戶下單筆最高可壓 ~$637 |
| 總曝險上限 | `max_gross_exposure_pct: 100.0` | 趨勢市 ≤60% / 震盪市 ≤30% | **無 regime 條件式硬上限**（見下方說明） |
| 板塊曝險 | `max_sector_pct: 40.0` | — | 合理 |
| 未平倉總風險 | `max_total_open_risk_pct: 6.0` | — | 合理，這是好的第二道防線 |

**regime 曝險是軟性建議、不是硬性上限**：`RegimeDetector` 算出 `exposure_pct`（RISK_ON=100 / NEUTRAL=60 / RISK_OFF=25 / CRISIS=0），但 `main.py` 只用它去乘進場股數（`if self.exposure < 100: shares = int(shares * self.exposure / 100)`），`Portfolio.check_book_limits()` 用的仍然是 config 寫死的 `max_gross_exposure_pct=100`。也就是說：即使 regime 判定「震盪市」，`Portfolio` 允許的總曝險上限依然是 100%，只是**新單**會被縮小 —— 已有的持倉不受影響，且如果多筆信號在同一 cycle 觸發，理論上仍可能疊加到接近 100% 曝險。這與你要求對比的「震盪市 ≤30%」有實質差距。

**波動率目標機制**：`DynamicPositionSizer.scale_shares()` 已經是一種輕量版波動率目標——ATR% > 5% 縮倉至 70%、> 3% 縮至 85%、VIX > 25 再乘 0.7——這個機制存在且合理，但**它只縮小股數，不會依波動率動態調整停損距離的『再平衡』**（停損已經是 ATR-based，兩者疊加時沒有做風險守恆檢查，即「縮股數同時 ATR 停損又變寬」可能讓實際 $ 風險不降反升）。

**回撤控制**：`check_drawdown()` 同時檢查「相對高位回撤 >10%」與「相對初始資本絕對虧損 >8%」，雙閘門合理。但 `max_absolute_loss: 8.0` 在 $1,275 帳戶上等於 $102 就全面停機——這個數字對應到你在 config 裡另外設的 `max_drawdown_limit: 10.0`（$127.5），兩者會幾乎同時觸發，變成事實上只有一道防線，不是兩道。

---

## 📊 數據管線審計

**IBKR/yfinance 雙源備援**：`fetch_symbol_data()` 邏輯正確——先試 IBKR，`raw is None or len(raw) < min_bars` 才 fallback 到 yfinance，這保證了資料量不足時會補源而非直接放棄。`quality_report()` 三段式檢查（結構完整性 → 新鮮度 → 單日異常波動）分層清楚，每個失敗階段都寫入 blotter 並可選擇性通知。

**做得好的細節**：`validate_ohlcv()` 檢查 `low <= close <= high` 的邏輯一致性，這是很多零售機器人會漏掉的健全性檢查；`MarketCalendar` 專門處理假日和半日市，`trading_days_between()` 用交易日而非日曆日算新鮮度，避免週末誤判數據過期。

**缺口**：
- 盤中引擎 (`intraday_engine.py`) 走**完全獨立**的抓取路徑（自己的 IBKR/yfinance fallback），沒有復用 `data_utils.quality_report()` 的品質閘門——盤中資料只檢查 `len(df) >= min_intraday_bars`，沒有新鮮度/異常值檢查。日線和分鐘線兩套資料品質標準不一致。
- `yf.download()` 呼叫沒有設定 timeout，理論上網路異常時可能長時間阻塞主循環（雖然被 try/except 包住，但阻塞期間整個 cycle 停滯，不是非阻塞失敗）。

---

## ⚙️ 執行引擎審計

**Bracket 訂單完整性**：三腳訂單（parent LMT / take-profit LMT / stop STP）在 `_build_bracket()` 正確設定 `parentId` 和 `transmit` 旗標（只有最後一腳 `transmit=True` 觸發整組送出），這是 IB API 的標準正確用法。`place_bracket_order()` 對 `stop_price<=0` 直接拒絕下單，避免無保護持倉——這點做得比很多機構級系統的入門版本都嚴謹。

**🔴 止蝕單監控缺口（你在提示詞中特別點名的風險，已在程式碼中確認存在）**：

```python
# order_manager.py track_bracket()
trade=(bracket.get("trades") or [None])[0],   # 只取 trades[0] = parent 訂單
```

`OrderManager.poll()` 只會輪詢 `managed.trade`（parent 進場單）的狀態，**完全不追蹤 stop-loss 和 take-profit 兩個子單**。這意味著：
- 如果券商因故拒絕或取消了 stop-loss 子單（例如超出當日漲跌停、流動性不足、券商端規則變更），機器人**沒有任何機制會發現**，`OrderManager.snapshot()` 回報的狀態只反映 parent 單，dashboard 會顯示「持倉正常」但實際上可能是裸倉。
- `reconcile()` 靠 `ib.fills()` 抓已實現盈虧能捕捉到「停損被觸發並成交」的情況，但抓不到「停損單被取消、根本沒有掛在市場上」的情況。

**部分成交處理**：`ManagedOrder.remaining` / `is_open` 邏輯正確，`poll()` 會累計 `newly_filled` 並寫入 blotter，標記 `"PARTIAL"` vs `"FILLED"`。這部分做得不錯，是少數幾個真正貼合機構標準的細節。

**訂單逾時**：`cancel_stale()` 只取消 `open_orders()`（即 parent 未完全成交的單），邏輯正確——但因為只追蹤 parent，同一問題延伸：如果 parent 已成交但 stop-loss 子單卡住變成孤兒單，`cancel_stale()` 抓不到它。

---

## 🧠 策略邏輯審計

**QuantEngine 因子權重（動能 35% / 成交量 25% / 波動壓縮 20% / 相對強弱 20%）**：程式碼與註解中沒有任何統計驗證依據（沒有 IC 分析、沒有因子單獨回測、沒有權重敏感度測試），是工程師憑經驗設定的權重，屬於「需要證據支持」的假設而非已驗證結論。這件事本身不是錯誤，但應該誠實標註「未經統計驗證」，且應該用 `backtest/engine.py` 對不同權重組合跑敏感度分析後再固化。

**🔴 致命整合 Bug：K 線信號的 `confidence` 是字串，風控層期望數字**

這是本次審計發現的最高優先級問題，證據鏈如下：

1. `core/trading_signals.py` 第 24 行，每個 `STRONG_BUY` 信號固定回傳：
   ```python
   "confidence": "HIGH",   # 字串，不是數字
   ```
2. `core/professional_mind.py` 第 266 行，`_score_execution()` 在**每一次** `approve_entry()`（也就是每一次真實買入信號都會走到）執行：
   ```python
   conf = float(signal.get("confidence", 0.5) or 0.5)   # float("HIGH") → ValueError
   ```
3. 這行會拋出 `ValueError: could not convert string to float: 'HIGH'`。
4. 呼叫鏈：`main.py::process_symbol()` → `handle_buy()` → `self.professional.approve_entry(...)` → `_score_execution()` 拋例外 → 沒有被 `approve_entry()` 內部捕捉 → 一路往上炸到 `main.py` 主循環的 `except Exception as e: logger.exception(f"分析 {symbol} 時發生錯誤: {e}")`。
5. **結果**：這個例外被當成「分析該股票時的隨機錯誤」記錄下來、`notifier.alert_exception()` 發告警，然後**這個 cycle 直接跳過該檔股票，不會下單**。因為每個 STRONG_BUY 信號都會觸發，等同於——**只要策略邏輯本身判斷該買，系統就會在最後一步自己炸掉，永遠不會真正送出委託單**。

**我如何確認這不是我的推測**：`tests/test_professional_mind.py` 裡僅有的 3 個測試全部手動建構 `signal = {"action": "STRONG_BUY", "confidence": 0.7}`（數字），從未使用 `trading_signals.py` 真實產出的字串格式；`tests/test_trading_signals.py` 則獨立驗證 `signal["confidence"] == "HIGH"`。**兩個模組的單元測試都各自通過，但從未有一個整合測試把兩者串起來跑過**——這正是為什麼 347 個測試全綠、CI 覆蓋率達標，這個會讓交易完全停擺的 bug 卻活到了審計這一刻。

**修復方式（一行）**：
```python
# core/trading_signals.py，把字串改成數值信心分數
"confidence": 0.8,   # 或依 candle["strength"] 動態給分，比固定字串更有資訊量
```
同時應在 `tests/` 新增至少一個**端到端整合測試**：真實跑 `TradingSignals.get_combined_signal()` 產生信號，把該信號原封不動餵給 `ProfessionalMind.approve_entry()`，斷言不拋例外——這種「模組 A 的輸出格式 = 模組 B 的輸入假設」的契約，光靠各自的單元測試永遠測不出來。

**K 線形態疊加邏輯的一致性問題**：`candle_patterns.py` 的 `strength` 是多個形態判斷**累加**的（鎚頭 +0.4、看漲吞噬 +0.6、十字星±0.3……），但 `entry`/`stop` 變數卻是**後面判斷覆蓋前面**（不是加權平均、不是取最高強度形態的值）。舉例：如果同一根 K 線同時滿足「鎚頭」（entry=high+0.01, stop=low-0.02）又滿足十字星蜻蜓型態，最終 `entry`/`stop` 只會是十字星那組值，即使鎚頭的訊號強度可能才是主要驅動力。這會讓 `strength` 分數和實際 `entry`/`stop` 價位在多形態共振時互相脫節。

---

## 📈 回測與驗證審計

**是否重用實戰程式碼**：部分重用——`backtest/engine.py` 確實 import 了 `QuantEngine`、`load_strategies`、`RiskManager`、`Portfolio`，這比大部分零售機器人「回測一套、實盤一套」誠實得多。

**但重用不完整，會系統性高估實盤表現**：`BacktestEngine.run()` **完全沒有調用**：
- `ProfessionalMind`（regime 判斷是否 STRATEGIC_CASH、ATR 停損覆蓋、市場結構過濾、PDT 限制、金字塔加倉規則、宏觀事件視窗）
- `IntradayEngine`（VWAP/開盤區間確認）
- `FundamentalFilter` / `NewsSentiment`（基本面與新聞過濾）
- `WatchlistManager`（動態觀察名單、板塊/相關性過濾）
- 任何手續費、滑點模型（實盤 `entry_with_slippage()` 有加 tick 滑點，回測用的是信號原始 `entry` 價，逢低估成本）

也就是說，回測看到的勝率/獲利因子，是在**沒有心態層否決、沒有盤中確認失敗、沒有手續費**的理想化條件下跑出來的——實盤會多出至少 6–7 道額外的拒絕關卡（見 §5 的 `approve_entry` 邏輯），實際交易頻率和回測會有明顯落差，且回測績效不能直接當作實盤預期的可靠估計。這是「回測與實盤脫鉤」型的前視偏差，不是傳統意義上「用到未來數據」，但效果類似：回測結果比實盤能達到的更樂觀。

**測試覆蓋率分佈**（347 個測試函式，按檔案統計）：
| 模組 | 測試數 | 備註 |
|---|---|---|
| `test_professional_mind.py` | **3** | 本次發現的致命 bug 所在模組，覆蓋最薄 |
| `test_position_sizer.py` | **3** | |
| `test_regime.py` | **4** | |
| `test_watchlist_manager.py` | **4** | |
| `test_intraday_engine.py` | **4** | VWAP pullback 雙重除以 100 的 bug（見下）所在模組 |
| `test_ibkr_connector.py` | 25 | |
| `test_market_calendar.py` | 31 | |
| `test_portfolio.py` | 22 | |

規律很清楚：**帶 🆕 標記的「新增機構級模組」測試數量最少**，而本次揪出的兩個實質性 bug（confidence 型別、VWAP pullback 雙重百分比）恰好都落在這批模組裡。CI 的 `--cov-fail-under=75` 是行覆蓋率，不是路徑/整合覆蓋率，寫幾個空跑的 happy-path 測試就能讓覆蓋率達標，但抓不到跨模組契約錯誤。

**另一個具體 bug（盤中執行）**：`intraday_engine.py` 第 190 行：
```python
pullback = float(self.cfg["vwap_pullback_pct"]) / 100.0     # 0.8 → 0.008
...
target = vwap * (1.0 + pullback * 0.01)                       # 0.008 又乘一次 0.01 → 0.00008
```
`config.yaml` 設定 `vwap_pullback_pct: 0.8`（意圖是 0.8%），但程式碼把百分比轉換除了兩次（一次 `/100`，一次又 `*0.01`），實際生效的回踩幅度只有 **0.008%**，等於這個「VWAP 回踩調整進場價」的功能形同虛設——調整後的價格永遠約等於 VWAP 本身（四捨五入到分後幾乎看不出差異）。`tests/test_intraday_engine.py` 沒有針對這個計算寫斷言，同樣是覆蓋率薄弱區的產物。

---

## 🚀 營運與部署審計

**Docker**：`Dockerfile` 用非 root 使用者執行（`useradd trader`），有基於 `state.json` 更新時間的 `HEALTHCHECK`（>30 分鐘沒更新視為不健康），這兩點都是正確的生產實踐。`docker-compose.yml` 拆 `bot` / `dashboard` / `ib-gateway`（社群維護的 `gnzsnz/ib-gateway`）三個服務，並在註解中誠實提醒「IBKR 需要定期重新驗證，Gateway 沒有官方鏡像，生產前請讀該專案文件」——這種誠實標註比隱瞞風險更值得信賴。

**日誌輪轉**：`logging_setup.py` 用 `RotatingFileHandler`（10MB × 5 backup），設定合理，且把 `ib_insync` 和 `urllib3` 的 log level 調到 WARNING 避免洗版。

**狀態持久化**：`TradingState.save()` 用「寫暫存檔 → `Path.replace()` 原子替換」，避免程式在寫入中途崩潰導致 state.json 損毀——這是教科書等級的正確做法，很多機器人會直接 `open(path,'w')` 覆寫，遇到斷電會丟失整個交易狀態。`schema_version` 欄位也讓未來狀態格式升級有向後相容的空間。

**優雅停機**：`request_shutdown()` 註冊 `SIGINT`/`SIGTERM`，`shutdown()` 在退出前完成 `order_mgr.poll()`（抓最後的成交狀態）→ `publish_state()` → 記錄 `SHUTDOWN` 事件 → `ibkr.disconnect()` → 發送通知，順序正確。`_sleep()` 用可中斷的輪詢睡眠（每 2 秒檢查一次 `shutdown_requested`），確保 `Ctrl+C` 不會卡在長 sleep 裡。

**缺口**：
- **`.env.example` 的 `TOTAL_CAPITAL=385.0` 與你實際帳戶 $1,275 不符**。系統啟動時如果 `.env` 沒同步更新，`RiskManager` 在 IBKR 連線建立、`reconcile()` 執行**之前**的所有計算（包括啟動時的第一次 `refresh_market_context`/日誌輸出）都會用錯的資本基準；連線後 `sync_capital()` 會用 broker 的 `NetLiquidation` 覆蓋，屬於「最終會自我修正，但啟動窗口期會用錯誤數字」的隱患。**部署前務必手動確認 `.env` 裡 `TOTAL_CAPITAL` 的值。**
- 沒有看到 CI 裡有針對 Docker image 的 build/smoke test（CI 只跑 `compileall` + `pytest`，沒有 `docker build` 驗證），Dockerfile 本身若有語法或依賴問題不會被 CI 攔截。

---

## 🎯 J Law / Martin Luk 風格對比

**M.E.T.A.（多重優勢匯聚）思維**：系統目前是「量化 Z-Score 過濾 + 均線結構過濾 + 量比過濾 + K 線形態」四個獨立條件的**布林 AND**（`trading_signals.py` 的 `tech_bullish AND candle bullish`），不是計分制的「N 個優勢中滿足幾個」confluence score。這意味著系統無法區分「4 個邊際都勉強達標」和「4 個邊際都強烈共振」——兩者目前產生的都是同一個 `STRONG_BUY` 標籤，沒有分級。建議把 `MindDecision.execution_score`（目前只用於記錄，1–10 分）**回饋進倉位大小**，而不只是寫進 journal——這樣接近你說的「多重優勢進場點」精神：優勢越多，倉位越大，而不是二元的買/不買。

**止蝕紀律**：不是固定 2%。主路徑用「K 線形態的 low − 0.02」，`ProfessionalMind` 之後可能再用 ATR 停損覆蓋（`atr_stop_price`，`multiplier=2.0`），只有在 `candle["stop"]` 為 `None` 時（`trading_signals.py` 沒有偵測到明確形態停損位）才退回固定的 `price - price*0.02`。這比死板的 2% 更貼近波動率，但**不符合你要求對比的「2% 固定止蝕」標準**——如果你希望的是嚴格 J Law 式紀律，這裡是設計哲學上的分歧，不是 bug，需要你確認要哪一種。

**動態倉位（趨勢市 ≤60% / 震盪市 ≤30%）**：如前述（§風險管理），目前 regime 只縮放**新單**股數，不是硬性覆蓋 `Portfolio` 的曝險上限，因此無法保證「震盪市總曝險 ≤30%」這種帳戶層級的約束會被遵守。

---

## 🔧 優先級優化建議

### 🔴 高優先級（Critical — 立即改善，否則系統無法真正交易或帶裸倉風險）

**1. 修復 `confidence` 型別 Bug（阻擋一切真實下單）**
- **步驟**：`core/trading_signals.py` 第 24 行，把 `"confidence": "HIGH"` 改為數值，建議依 `candle["strength"]` 動態算分，例如 `"confidence": min(1.0, 0.5 + abs(candle["strength"]) * 0.3)`。
- **同步動作**：新增一個整合測試 `tests/test_signal_to_mind_integration.py`，真實跑 `TradingSignals → ProfessionalMind.approve_entry`，斷言不拋例外。
- **預期改善**：這是唯一一項能決定系統「能不能交易」的修復，優先級高於本清單其餘所有項目。

**2. 追蹤 Bracket 訂單的 stop-loss / take-profit 子單狀態**
- **步驟**：`OrderManager.track_bracket()` 目前只 `track(trades[0])`，應改為對 `bracket["trades"]` 全部三腳分別 `track()`（用各自的 `order.orderId` 當 key），`poll()` 迴圈遍歷所有子單，若偵測到 stop-loss 腳的狀態變成 `Cancelled`/`Inactive` 且對應持倉仍存在，立刻觸發 `notifier.alert_order_issue()` 並考慮自動用市價單補掛保護性停損。
- **預期改善**：直接解決你提示詞裡點名的「止蝕單未被券商接收」風險，避免裸倉。

**3. 修復 VWAP pullback 雙重百分比換算 bug**
- **步驟**：`core/intraday_engine.py` 第 190/193/195 行，`pullback = float(self.cfg["vwap_pullback_pct"]) / 100.0` 後面不應該再 `* 0.01`，直接用 `target = vwap * (1.0 + pullback)`（若要往上偏移）或依買賣方向決定正負號。
- **預期改善**：讓「盤中回踩 VWAP 確認」這個你在 config 裡特別調校的參數真正生效，而不是形同虛設。

**4. 確認並修正 `.env` 的 `TOTAL_CAPITAL`**
- **步驟**：部署前執行 `python scripts/diagnose_env.py`（已存在的腳本）並手動確認 `.env` 內 `TOTAL_CAPITAL=1275`（或你的實際淨值），不要依賴預設的 385。
- **預期改善**：避免啟動窗口期（IBKR reconcile 之前）用錯誤資本基準計算風險百分比。

### 🟡 中優先級（Enhancement — 中期優化，提升穩健性與貼近機構標準）

**5. 讓 regime 曝險成為硬性上限，而非只縮放新單**
- **步驟**：在 `Portfolio.check_book_limits()` 增加一個由 `main.py` 傳入的動態 `regime_exposure_cap` 參數，取代寫死的 `max_gross_exposure_pct`；`TradingBot.refresh_market_context()` 算出 `self.exposure` 後直接寫入 `self.portfolio.max_gross_exposure_pct = self.exposure`（震盪市自動降到 25–60% 上限，不只是新單縮量）。
- **預期改善**：真正落實「震盪市 ≤30%、趨勢市 ≤60%」的動態倉位管理，不只是新單受限、舊倉不受限。

**6. 收緊單一持倉集中度上限，貼近 J Law 15–20% 標準**
- **步驟**：$1,275 帳戶下，把 `risk.max_position_pct` 與 `portfolio.max_symbol_pct` 從 50% 調整到 20%（單筆最高 ~$255），並考慮把兩個設定合併成單一事實來源（`Portfolio` 讀取後注入給 `RiskManager`，而非各自從 config 讀一份）。
- **預期改善**：小資金帳戶下，50% 集中度代表 1–2 筆交易就能決定帳戶生死，20% 上限能讓系統至少維持 5 筆分散。

**7. 把 `execution_score`（1–10 分）接回倉位大小，實現真正的 M.E.T.A. confluence 分級**
- **步驟**：`ProfessionalMind.approve_entry()` 已經算出 `execution_score`，目前只寫入 journal。在 `handle_buy()` 增加：`if mind_decision.execution_score < 6: shares = int(shares*0.5)`；`execution_score >= 9` 才給滿倉係數。
- **預期改善**：讓「多重優勢共振」的信號真的比「勉強達標」的信號拿到更大倉位，貼近 M.E.T.A. 精神。

**8. 回測引擎接入 `ProfessionalMind`，縮小回測/實盤落差**
- **步驟**：`BacktestEngine.__init__` 增加可選的 `professional_mind` 參數，`run()` 迴圈在產生 `STRONG_BUY` 信號後、真正開倉前，插入 `mind.approve_entry(...)` 判斷；同時在 pnl 計算加入固定手續費模型（例如每筆 $1 或 IBKR 分層費率）。
- **預期改善**：讓回測績效數字更貼近實盤能達到的水準，避免對系統獲利能力過度樂觀。

**9. 修正 K 線形態疊加時 entry/stop 與 strength 脫節的問題**
- **步驟**：`candle_patterns.py` 改成「記錄觸發強度最大的形態」而非「最後判斷覆蓋前面」，例如維護 `best_pattern = max(triggered_patterns, key=lambda p: abs(p['strength']))`，`entry`/`stop` 一律取自 `best_pattern`。
- **預期改善**：避免強度分數和進出場價位在多形態共振時互相矛盾。

**10. 盤中資料接入與日線一致的品質閘門**
- **步驟**：`IntradayEngine.fetch_bars()` 回傳後，用 `data_utils.detect_price_outlier()` 對分鐘線也跑一次異常值檢查（沿用相同的 `max_daily_move_pct` 概念，換算成分鐘級門檻）。

### 🟢 低優先級（長期優化）

**11. 為 `QuantEngine` 的因子權重補上統計驗證**：用 `backtest/engine.py` 對 35/25/20/20 做敏感度掃描（例如網格搜尋 ±10% 權重變化對 `profit_factor` 的影響），把「工程師經驗值」升級為「有實證支持的權重」，並在 docstring 標註驗證方法與樣本期間。

**12. `handle_buy()` 拆分為 `EntryPipeline` 類別**，每個階段（滑點/盤中確認/倉位計算/相關性/心態審批/預驗證/送單）獨立成方法並個別單元測試——這會讓下一個「模組間契約不匹配」型的 bug 更容易在 CI 就被抓到，而不是活到生產環境。

**13. CI 增加 Docker build smoke test**：`docker build` + 啟動容器跑 `--once --dry-run` 驗證 image 本身可運作，而不只驗證原始碼可 import。

---

## 💎 總結

這套系統的**工程紀律**（狀態持久化、稽核軌跡、多層風控、CI 覆蓋率門檻、Docker 生產化）已經達到相當認真的零售機構級水準，遠超一般個人交易機器人的常見水準。但這次逐檔審計揪出的 `confidence` 型別 bug，是一個**會讓系統在最後一哩路完全失去交易能力**、卻因為單元測試各自為政而從未被抓到的典型「整合層盲點」——這也印證了你在提示詞裡強調的方向是對的：光看模組化架構和測試數量不夠，必須真的追蹤資料在模組邊界之間如何流動。

**修復第一項（confidence bug）之前，不建議開啟 `auto_trade: true`**——目前設定檔裡它是 `false`，這是對的，但也代表這個 bug 至今可能還沒有在你的實盤/紙上交易中曝光過（因為系統一直處於 signal-only 模式）。開啟自動交易前，強烈建議先跑一次 `--dry-run` 或 `--once`，確認至少一個 STRONG_BUY 信號能完整走到「送出 Bracket 訂單」而不被 `ProfessionalMind` 吞例外，再正式上線。

在 $1,275 的小資金規模下，比起追求更複雜的因子模型，**優先修復阻斷交易的 bug、收緊單一持倉集中度、把 regime 曝險變成硬上限**這三件事，投資報酬率會遠高於任何策略邏輯的微調。
