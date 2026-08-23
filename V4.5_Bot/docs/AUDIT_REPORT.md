# V4.5 Trading Bot — AI 深度審計報告

> **Note:** Critical fixes from this report (confidence crash, bracket tracking, VWAP pullback, risk limits, `data/` folder) were applied in commits `9c6390b`–`05848c9` on branch `cursor/v45-institutional-upgrade-16b9`. See [docs/README.md](README.md).

**審計對象**：V4.5_Bot（`V3_Bot-cursor-v45-institutional-upgrade-16b9.zip`）
**審計方式**：全量原始碼閱讀（main.py、core/ 33 個模組、backtest/、tests/ 347 個測試函式），非僅憑檔名或 README 推測
**帳戶規模**：約 $1,275（config.yaml 預設值目前是 $385，見下方 🔴 立即改善）

---

## 📊 執行摘要

**整體評分：6.5 / 10**（機構級「骨架」已具備，但存在至少 1 個會讓每筆買入信號當掉的邏輯錯誤，以及風控參數與 J Law 標準有結構性落差）

這套系統在架構分層、稽核軌跡、狀態持久化、7 層風控閘門的「形」上，確實達到了業餘專案少見的成熟度：`professional_mind.py` 的多重審批鏈（流動性 → 結構 → ATR停損 → PDT → 加倉規則 → 總經事件）是這份專案中設計得最好的部分。但深入追蹤資料流之後，發現三個實質問題會讓系統的「神」打折扣。

**三大優勢**
1. **風控閘門確實是分層且互相獨立的**：`RiskManager`（帳戶層）、`Portfolio`（組合/板塊層）、`ProfessionalMind`（決策層）三者各司其職，沒有互相繞過的漏洞；`check_gates()` 在下單前会依序檢查 halt → drawdown → daily loss → book limits，順序正確。
2. **停損保護在券商端而非機器人端**：`place_bracket_order` 拒絕任何無停損價的下單（`if not stop_price or stop_price <= 0: return None`），且用的是 bracket/OCA 結構，即使機器人程式崩潰，停損單仍留在 IBKR 伺服器上——這是很多零售機器人忽略的關鍵細節。
3. **回測引擎重用了實盤的 `QuantEngine`／策略／`RiskManager`**，架構上確實杜絕了「回測一套邏輯、實盤另一套邏輯」的常見陷阱。

**三大劣勢**
1. **🔴 `professional_mind.py` 有一個會讓每一筆 STRONG_BUY 訊號在 `approve_entry()` 內丟出 `ValueError` 而永遠無法下單的 bug**（`float("HIGH")`）。只要 `professional_mind.enabled: true`（目前設定就是 true），auto_trade 模式下**實際上不會有任何一筆買單成功送出**，全部被外層 try/except 吃掉、寫進 log，但操作者若沒有仔細看 log 完全不會發現「機器人其實從沒進過場」。
2. **風控參數與訪客提到的 J Law 標準有 2–3 倍的落差**：單筆風險上限 2.0%（未觸發連虧降檔前）、單一持倉集中度上限 50%、總曝險上限 100% 皆遠寬於 1–1.5% / 15–20% / 60% 的目標，且 regime 判斷出的建議曝險（如 RISK_OFF 時 25%）**只影響新倉股數，不會回頭收緊 `Portfolio` 的硬性總曝險上限**。
3. **量化引擎的「波動率壓縮」因子（權重 20%）在目前的 3 個月資料窗口下幾乎必為 0**——不是設計錯誤，是資料長度不足以支撐計算所需的回溯視窗，導致標榜的 35/25/20/20 四因子模型實際上只有 3 個因子在運作。

---

## 🏛️ 架構審計

### 耦合與循環依賴
沒有發現循環 import。依賴方向清楚：`main.py` → `core/*`（單向），`core/professional_mind.py` 再往下組合 6 個子模組（`position_sizer`、`economic_calendar`、`market_structure`、`liquidity_guard`、`pdt_guard`、`pyramid_manager`、`portfolio_analytics`、`theme_registry`）。這是典型的 façade/orchestrator 模式，合理。

### 「上帝物件」評估
- `main.py` 的 `TradingBot` 類別 758 行、對 `self.` 的引用 278 次，是全案最大的類別。它同時扮演：組態解析、IBKR 生命週期、資料獲取、訊號迴圈、下單、對帳、關機——**責任數量偏多**，但因為每個責任都委派給對應模組（`self.ibkr`、`self.risk_mgr`、`self.order_mgr`…）執行，`TradingBot` 本身更像是「協調器」而非把邏輯全塞進自己身體裡的真上帝物件。可以拆，但不是燃眉之急。
- 建議拆分方向：把 `run()` 內的主迴圈（cycle 邏輯、gate 檢查、symbol 迴圈）抽成獨立的 `TradingCycle` 類別，`TradingBot.__init__` 只做組裝（純 DI container），會讓單元測試主迴圈變得容易很多——目前 `main.py` 沒有對應的 `test_main.py`，主迴圈邏輯完全沒有被測試覆蓋。

### 設定與行為漂移（隱性技術債）
`config.yaml` 中 `zscore.overheat_threshold: 2.5` 與 `zscore.best_zone_max: 1.5` 兩個鍵**在整個原始碼中從未被讀取**（只有 `best_zone_min` 有被用到）。`trading_signals.py` 裡的上限 1.5 是寫死的常數，跟 config 裡的 `best_zone_max` 剛好同值只是巧合——如果之後有人改 `best_zone_max` 想調整上限，改了也不會生效。這種「看起來可調、實際上寫死」的設定是排查時間的隱形殺手，建議做一次「config key 使用率」稽核，刪掉或接上所有孤兒鍵。

---

## 🛡️ 風險管理審計

### 對比 J Law 標準

| 項目 | J Law 建議 | 本系統設定 | 落差 |
|---|---|---|---|
| 單筆交易風險 | 1–1.5% | `max_risk_percent: 2.0`（連虧 3 次才降至 1.0%） | 偏高 33–100%，且要先虧 3 次才會收斂到標準值 |
| 單一持倉集中度 | ≤ 15–20% | `max_position_pct: 50.0` / `portfolio.max_symbol_pct: 50.0` | 2.5–3.3 倍過寬 |
| 總倉位曝險 | 趨勢市 ≤60% / 震盪市 ≤30% | `max_gross_exposure_pct: 100.0`（靜態，regime 不會回頭收緊它） | 無上限式的動態收緊 |
| 停損紀律 | 固定 2% | 已升級為 **ATR 動態停損**（`atr_multiplier: 2.0`），比固定 2% 更專業，但也代表脫離了 J Law 的「固定紀律」精神 |（此項是合理的升級，不算劣化）|

**具體問題**：`max_position_pct`（RiskManager）與 `max_symbol_pct`（Portfolio）兩個名字不同、位置不同、但概念幾乎重疊，都是「單一標的佔比上限」，目前剛好同為 50%，但兩處要手動同步維護，未來很容易改一個忘記改另一個而產生風控盲點。建議合併成單一事實來源（Single Source of Truth），例如統一放在 `portfolio` 區塊，`RiskManager.calculate_position_size` 改成向 `Portfolio` 查詢上限。

**Regime 曝險與帳戶硬上限脫節**：`regime.py` 算出 RISK_OFF 時建議曝險 25%，但這個數字只在 `handle_buy()` 裡拿來乘新股數（`shares = int(shares * self.exposure / 100)`），**不會收緊 `Portfolio.max_gross_exposure_pct`**。也就是說：如果系統已經在 RISK_ON（100% 曝險）時建了倉，之後 regime 轉為 RISK_OFF，既有持倉的總曝險上限依然是設定檔裡寫死的 100%，不會被要求減倉。regime 只管「進」不管「守」。

**波動率目標（Volatility Targeting）**：目前完全沒有這個機制。有的是「單筆停損距離會依 ATR 調整」（position sizing 層級），但沒有「整體組合曝險依市場實現波動率動態調整」（portfolio 層級）。以 $1,275 的帳戶規模，這件事的 ROI 其實不高——建議列為 🟢 低優先級的中長期項目，先把上面兩個具體落差修掉更划算。

### 小資金限制下的實務問題
以 $1,275 資本、`price_limit=40`、`max_shares=20` 推算：`max_position_pct=50%` 換算成 $ 上限是 $637.5，若股價接近 40 元上限，20 股成本即 $800，會被 50% 集中度上限砍到約 15–16 股。也就是說在目前參數下，`max_shares=20` 這個上限本身很少真正生效，實際限制因子幾乎永遠是集中度上限或風險金額上限——這代表 `max_position_pct=50%` 才是真正決定倉位大小的關�s鍵參數，把它從 50% 調到 15–20%（貼齊 J Law）在小資金帳戶上影響會非常明顯（單筆最大部位直接砍掉 60–70%），這是投入產出比最高的一項風控調整。

---

## 📊 數據管線審計

### IBKR / yfinance 雙源備援
`fetch_symbol_data()` 邏輯：先試 IBKR（若已連線），資料不足 `min_bars` 再 fallback 到 `yfinance`。邏輯正確，但有兩個實務風險：
1. **VIX 只用 `yf.Ticker("^VIX")`，沒有 IBKR 備援路徑**，且僅重試 3 次、每次固定 sleep 1 秒。Yahoo Finance 免費端點對高頻請求（`intraday_mode` 下每 60 秒一輪）容易被限流；一旦連續失敗，`current_vix` 會沿用上一次快取值繼續交易，`risk_mgr.check_vix()` 因此可能長時間用過期 VIX 值做風控判斷，且沒有任何告警。建議：VIX 失敗次數達到閾值時應觸發 `notifier.alert_data_failure`（目前只有個股資料失敗才有告警）。
2. **`get_historical_data(duration="3 M")` 對量化引擎不夠長**（見下方「策略邏輯審計」——這其實是資料管線層的設定失誤，不是量化邏輯本身的錯）。

### 資料品質閘門
`data.min_bars=60`、`max_age_trading_days=2`、`max_daily_move_pct=40%`、`max_consecutive_failures=3` 的組合覆蓋了新鮮度、異常值、樣本數三個面向，設計方向正確。40% 單日漲跌幅閾值對於本身就鎖定 $5–40 低價股（`fundamental.min_market_cap=5億`、`watchlist.scanner.max_price=40`）的策略來說是合理寬容值（低價股本來波動就大），不需要調整。

---

## ⚙️ 執行引擎審計

### Bracket 訂單完整性
`place_bracket_order` 本身邏輯完整：拒絕零停損訂單、優先使用 `ib_insync.bracketOrder()`（會自動建立 OCA 群組，一腿成交另一腿自動取消）。

**🔴 但備援路徑（手動組裝 bracket）有真實的雙腿同時成交風險**：`_build_bracket()` 的 fallback 分支（當 `self.ib` 沒有 `bracketOrder` 方法時觸發）手動組裝 parent/take_profit/stop_loss 三張單，**卻沒有替 take_profit 與 stop_loss 設定 `ocaGroup`／`ocaType`**。正常 IBKR 對「同一 parentId 底下的兩個子單」不會自動視為互斥（OCA 需要顯式群組），也就是說如果這條路徑被觸發（例如未來改接非 `ib_insync` 的 IBKR 包裝、或用 mock/stub 測試環境意外流到實盤設定），停利單與停損單有可能都被送出、都掛在市場上，行情劇烈波動時兩腿都成交，導致部位方向反轉或裸露曝險。目前用真正的 `ib_insync` 時這條路徑不會被觸發（`bracketOrder` 一定存在），風險是「休眠地雷」而非「現正引爆」，但既然程式碼裡明寫了 fallback，就該把它修對，而不是靠「反正用不到」來自我安慰。

### 部分成交處理
`OrderManager.poll()` 有正確處理部分成交：`newly_filled = filled - managed.filled_qty`，並把 `PARTIAL`/`FILLED` 狀態寫進 blotter，設計沒問題。

**逾時取消的殘留風險**：`cancel_stale()` 只取消 `managed.trade`（也就是 parent 單），沒有主動呼叫 `cancel_orders_for_symbol()` 清掉對應的 take_profit/stop_loss 子單。如果 parent 尚未成交就逾時取消，正常情況下 IBKR 會自動連帶取消尚未觸發的子單（因為子單依附在未成交的 parent 上），但如果 parent **已經部分成交**（`filled_qty > 0`）又被判定逾時取消，此時已成交的部位仍持有，其停損/停利子單理論上應該繼續存活以保護這筆部位——但目前程式碼是「一律取消」，沒有區分「parent 完全未成交」與「parent 部分成交」這兩種情況，後者若被誤取消，等於讓已經進場的部位裸露、失去停損保護。建議在 `cancel_stale()` 加一個判斷：`filled_qty > 0` 時只取消未成交的殘量，保留已成交部分對應的停損單。

---

## 🧠 策略邏輯審計

### 因子權重 35/25/20/20 的統計依據
原始碼裡沒有看到任何回測掃描/最佳化紀錄能證明這組權重是資料驅動選出來的，程式碼註解與命名也沒有引用任何論文或研究，判斷是**經驗設定值，而非統計估計值**。這不是錯誤，但既然審計要求「統計依據」，誠實的答案是：目前沒有。若要補上，`backtest/engine.py` 已經有現成骨架，可以做一次「單因子 IC（Information Coefficient）分析」——把 z_momentum / vol_score / z_volatility / z_rs 個別對未來 N 日報酬做相關性回測，用實際數據反推權重，而不是繼續沿用四等分附近的權重。

### 🔴 波動率壓縮因子在目前設定下結構性失效（新發現，未在原始審計要求中被提及，但影響重大）
逐行推算 `QuantEngine.dynamic_score()` 的資料需求：
- `compression_scores` 迴圈跑 `range(60, len(df))`，每次都要往前抓 50 根 K 棒算 ATR50，所以要有意義地產生分數，`len(df)` 至少要 61。
- 但 `z_volatility` 這個分數本身還要再對 `compression_scores` 序列做一次 **window=60 的 rolling z-score**（`calculate_zscore(vol_series, 60)`），程式碼裡明確寫了保護：`if len(vol_series) >= 60: ... else: z_volatility = 0.0`。
- 這代表：`len(compression_scores) = len(df) - 60` 必須 **≥ 60**，也就是 `len(df) 必須 ≥ 120（約 5–6 個月的交易日）**，`z_volatility` 才有機會不是 0。

而目前資料抓取設定（`ibkr_connector.get_historical_data(duration="3 M")` 與 `main.py` 的 `yf.download(period="3mo")`）大約只能拿到 **60–65 根日 K**，遠低於 120 的門檻。**結果是：z_volatility 幾乎恆為 0.0，20% 權重的因子在實盤中從未真正貢獻分數**，`final_score` 實際上是三因子模型（momentum 35% + volume 25% + relative_strength 20%，等於在剩下 80% 權重裡重新分配），而系統、回測報告、儀表板上顯示的「四因子綜合分數」名不符實。這是一個純粹靠邏輯推導就能發現、且很容易驗證的問題（只要印出 `z_volatility` 觀察是否長期為 0 即可證實）。

**修法**：把 `data.duration`／`yf.download(period=...)` 改成至少 `"6 M"` / `period="6mo"`（抓 ~125 個交易日），或是把 `dynamic_score` 內部的 60/50/60 三個窗口依比例縮小（例如壓縮窗改 10/30，z-score 窗改 30），讓它在 3 個月資料下真正能算出非零值。前者改動小、風險低，優先採用。

### K 線形態與技術信號結合
`get_combined_signal()` 要求「K 線看漲形態 **且** 技術面同時看漲」才觸發 STRONG_BUY（AND 邏輯，非 OR），這符合 M.E.T.A.（多重優勢匯聚）精神的雛形——單一訊號不夠、需要兩個獨立系統同時確認。但目前只有「K線 + 技術面」兩個維度，沒有第三個獨立維度（例如成交量結構、期權流、機構籌碼），M.E.T.A. 的「多重」通常指 3 個以上互相獨立的優勢共振，目前設計比較接近「雙重確認」。

---

## 📈 回測與驗證審計

### 回測是否重用實盤程式碼
是的，`backtest/engine.py` 直接 import `QuantEngine`、`load_strategies`、`RiskManager`、`Portfolio`，這點做得很紮實，避免了「回測邏輯 A、實盤邏輯 B」的常見分裂問題。

### 前視偏差（Look-ahead Bias）檢查
逐行檢查 `BacktestEngine.run()` 的迴圈順序：
1. 每個 `index`，先用 `window = df.iloc[: index + 1]`（包含當根 K 棒的完整 OHLC）算訊號；
2. 若觸發 `STRONG_BUY`，**進場價直接採用當根 K 棒的收盤價**（`context.price = price = bar["close"]`，且 `entry = signal["entry"]` 是由 `TradingSignals` 用同一個 `price` 算出的）。

這是一個**輕微但真實的前視偏差**：現實中你要等收盤價出現才能確認訊號成立，但確認的當下已經來不及用「當根收盤價」成交——最早只能在下一根開盤price成交。目前回測等於假設「訊號出現的瞬間就能以當根收盤價精準成交、零延遲、零滑價」，這會讓回測績效系統性偏樂觀。相較之下，**實盤 `main.py` 的 `entry_with_slippage()` 有加一格滑價**，回測完全沒有對應處理，兩者存在「回測比實盤樂觀」的落差，應被視為需要修正的方法論缺陷，而不只是無傷大雅的簡化。

**建議**：把回測的進場邏輯改成「訊號在 bar[index] 收盤後產生 → 在 bar[index+1] 的開盤價（或開盤價+滑價）成交」，並在 `_check_exit` 對稱地處理停損/停利──目前 `_check_exit` 用 `bar` 的 low/high 判斷觸價，這部分沒有前視問題（只在成交當根之後的未來K棒才會被拿來檢查），問題只出在**進場**這一格。

### 效能問題（次要，但值得標出）
`QuantEngine.dynamic_score()` 內的 `compression_scores` 迴圈是 `O(視窗長度)`，而 `BacktestEngine.run()` 對每一根 K 棒都重新呼叫一次 `dynamic_score(window)`，`window` 隨 index 增長——整體是 **O(N²)** 複雜度。對單一標的、63 根 K 棒的日線回測影響不大，但如果未來要對 `watchlist.scanner.max_scan=120` 檔股票、或改用 5 分鐘 K 棒做長週期回測，會明顯變慢。可以用 pandas 向量化（`rolling().max()/rolling().min()` 取代 Python for-loop）在不改變結果的前提下大幅加速。

### 測試覆蓋
`tests/` 內有 347 個測試函式、涵蓋幾乎每個 core 模組，這是同類個人專案裡少見的紀律。但發現一個**測試盲點正好對應到上面那個 🔴 confidence bug**：`tests/test_professional_mind.py` 裡呼叫 `approve_entry` 用的假訊號是 `{"action": "STRONG_BUY", "confidence": 0.7}`（直接給 float），而**實際訊號來源 `trading_signals.py` 給的是字串 `"HIGH"`**（`tests/test_trading_signals.py` 也驗證了 `signal["confidence"] == "HIGH"`）。也就是說：兩個模組的單元測試都各自通過，卻沒有一個「整合測試」把 `TradingSignals.get_combined_signal()` 的真實輸出餵給 `ProfessionalMind.approve_entry()`，才會讓這個貫穿全系統、影響「機器人到底會不會下單」的 bug 活到現在沒被抓到。這是本次審計裡最有價值的具體發現，也是「單元測試覆蓋率高≠系統正確」的教科書案例——建議新增至少一支端到端測試：從 `process_symbol()` 開始、一路跑到 `handle_buy()`，斷言 dry-run 模式下不會拋出例外。

---

## 🚀 營運與部署審計

`Dockerfile`／`docker-compose.yml` 整體水準相當專業：非 root 使用者執行、healthcheck 檢查 `state.json` 是否在 30 分鐘內更新過（能抓到「容器活著但主迴圈卡死」這種殭屍狀態）、`logs/` 掛 volume 持久化、`ib-gateway` sidecar 有清楚註解說明兩階段驗證與 `IBKR_AUTO_RESTART_TIME` 的取捨。日誌輪轉用 `RotatingFileHandler`（10MB × 5 份）設定合理。

`shutdown()` 方法有做到：poll 一次未結訂單狀態 → 存檔 → 記錄 blotter → 斷開 IBKR → 發送通知，順序正確，是「優雅停機」而非直接砍掉行程。

**唯一可以加強的**：`docker-compose.yml` 沒有替 `bot` 服務設定資源限制（`mem_limit` / `cpus`），也沒有 `depends_on` 的健康檢查條件（目前 `depends_on: - ib-gateway` 只保證啟動順序，不保證 `ib-gateway` 真的已完成登入），若 `ib-gateway` 尚未完成 2FA 驗證，`bot` 容器可能在連線目標還沒 ready 時就開始重試，雖然 `connect()` 本身有 retry+exponential backoff（1s→2s→4s…上限 30s，最多 10 次)，實務上通常夠用，但仍建議把 `depends_on` 改成 `condition: service_healthy`（需替 ib-gateway 加 healthcheck）。

---

## 🎯 J Law / Martin Luk 風格對比

- **M.E.T.A.（多重優勢匯聚）**：目前是「K線形態 + 技術面 Z-Score」雙重確認，尚未納入第三個獨立維度（如成交量結構背離、跨市場相對強度、期權流）。建議下一版把 `market_structure.py` 已有的「吸籌/派貨階段判斷」正式納入訊號生成的必要條件（目前只在 `professional_mind.approve_entry` 的加分/扣分項出現，不是 `TradingSignals` 的硬性 gate），讓它從「軟性心理加分」升級為「第三重確認」。
- **止蝕紀律**：已從「固定 2%」升級為 ATR 動態停損，這是比 J Law 原始建議更專業的做法（波動大的股票給更寬的停損空間，避免被雜訊洗出場），方向正確，不建議走回頭路改回固定 2%。
- **倉位管理的趨勢/震盪動態調整**：`regime.py` 有算出 `risk_on_exposure=100 / neutral_exposure=60 / risk_off_exposure=25`，數字本身跟「趨勢市 ≤60%、震盪市 ≤30%」的精神接近，**但如前述「風險管理審計」所說，這個建議值目前只影響新倉，沒有回頭收緊帳戶硬上限**，是「有計算、沒強制執行」的落差。

---

## 🔧 優先級優化建議

### 🔴 高優先級（Critical，應立即修正）

1. **修正 `professional_mind.py` 的 confidence 型別崩潰**
   `core/professional_mind.py:266`：`conf = float(signal.get("confidence", 0.5) or 0.5)`，但 `TradingSignals` 給的是字串 `"HIGH"`。
   做法：改用映射表 `{"HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.3}.get(signal.get("confidence"), 0.5)`，或直接讓 `TradingSignals.get_combined_signal` 回傳數值型 `confidence`（更徹底，順便讓 `_score_execution` 的評分更有意義）。
   **預期改善**：這是目前唯一會讓 auto_trade 模式「完全無法下單」的問題，修完之後系統才算真正「可用」，優先度高於本清單所有其他項目。

2. **修正 config.yaml 的資本額**
   `capital.total` 預設 `385.0`，但實際帳戶約 $1,275。若沒有另外設定環境變數 `TOTAL_CAPITAL`，所有部位大小、風險金額、集中度計算都會用錯誤的基準。
   做法：直接改 `capital.total: ${TOTAL_CAPITAL:-1275.0}`，或在 `.env` 明確設定 `TOTAL_CAPITAL=1275`。

3. **補上手動 bracket fallback 的 OCA 群組**
   `core/ibkr_connector.py:_build_bracket()` 的 fallback 分支替 `take_profit` 與 `stop_loss` 加上相同的 `ocaGroup`（例如 `f"OCA_{symbol}_{int(time.time())}"`）與 `ocaType=1`。
   **預期改善**：消除「兩腿都成交、部位反轉」的尾部風險，即使目前這條路徑很少被觸發，屬於「修一次、永久排除」的低成本高效益項目。

4. **把單一持倉集中度上限從 50% 調到 15–20%**
   同步修改 `risk.max_position_pct` 與 `portfolio.max_symbol_pct`（並考慮合併成一個設定值，見架構審計）。
   **預期改善**：在 $1,275 帳戶上，這一項改動會直接把單筆最大部位金額砍到目前的 30–40%，是本清單中對實際風險曝險影響最大的單一改動。

5. **把總曝險上限依 regime 動態調整**
   在 `check_gates()` 或 `Portfolio.check_book_limits()` 中，把 `max_gross_exposure_pct` 改成 `min(config值, self.exposure)`（即 regime 建議的曝險上限），而不只是拿 `self.exposure` 去乘新倉股數。
   **預期改善**：讓「趨勢市 100% / 震盪市 60% / 危機 0%」真正對既有持倉生效，而不只是對新倉生效，補上訪客提到的「動態調整」缺口。

### 🟡 中優先級（Enhancement，建議 1–2 個月內處理）

6. **修正資料窗口，讓波動率壓縮因子真正生效**：把歷史資料抓取時長從 `"3 M"` / `period="3mo"` 改為至少 `"6 M"` / `period="6mo"`。改動集中在 `main.py:fetch_symbol_data` 與 `core/ibkr_connector.py:get_historical_data` 呼叫處，風險低。**預期改善**：讓標榜的 35/25/20/20 四因子模型名實相符，而不是實際上只有三個因子在運作。
7. **修正回測的前視偏差**：進場改成「訊號 K 棒收盤後 → 下一根開盤成交」，並加入與實盤一致的滑價模型。**預期改善**：讓回測績效與實盤表現的落差縮小，避免對系統過度樂觀。
8. **補齊 `sector_map`**：目前 watchlist 裡的 F、SOFI、PLUG、SNAP、HOOD、NIO、INTC、AAL 全部落在 `sector_map` 之外，會被歸類成 "UNKNOWN"，導致板塊集中度風控（`max_sector_pct=40%`）對這些標的形同虛設。**預期改善**：讓板塊分散風控對實際交易的股票真正生效。
9. **`cancel_stale()` 區分「parent 未成交」與「parent 部分成交」**：只取消未成交殘量，已成交部位保留停損保護。**預期改善**：避免逾時取消誤傷已建立的部位。
10. **VIX 抓取失敗要告警並考慮 IBKR 備援**：目前只有個股資料連續失敗會通知，VIX 失敗只是靜默沿用舊值。**預期改善**：避免整個 regime/風控判斷長期建立在過期波動率指標上而不自知。

### 🟢 低優先級（中長期優化）

11. **統計驗證因子權重**：用回測資料對四個因子做單因子 IC 分析，用數據反推權重取代目前的經驗設定。
12. **導入第三重確認維度，讓訊號生成更貼近 M.E.T.A.**（例如把 `market_structure.py` 的吸籌/派貨判斷從軟性加分升級為硬性 gate）。
13. **拆分 `main.py` 主迴圈成獨立可測試的 `TradingCycle` 類別**，補上目前完全缺失的主迴圈整合測試。
14. **向量化 `QuantEngine.compression_scores` 迴圈**，降低回測在大規模掃描場景下的 O(N²) 效能瓶頸。
15. **組合層波動率目標機制（Volatility Targeting）**：待前面 14 項處理完、且有更多實盤/回測數據支撐後再評估投入，現階段 ROI 不高。

---

## 💎 總結

這套系統的「工程紀律」是真的：347 個測試、不可篡改的 blotter、bracket 訂單優先於機器人存活性的停損設計，這些都是很多號稱「機構級」的個人交易機器人做不到的。但這次逐行審計也證明了一件事——**測試數量不等於系統正確性**：一個字串 `"HIGH"` vs 浮點數 `0.7` 的型別不一致，就足以讓整個 auto_trade 模式失去下單能力，而 347 個測試裡沒有一個抓到它，因為問題出在模組之間的「縫」而不是模組內部。

在 $1,275 的帳戶規模上，比起任何演算法優化，**最值得優先投入的是兩件事**：先讓機器人真的能下單（修 confidence bug），再讓它下的單不要太大（集中度上限從 50% 收到 15–20%）。這兩項加起來的改善幅度，會遠大於本報告裡任何一項策略邏輯的微調。
