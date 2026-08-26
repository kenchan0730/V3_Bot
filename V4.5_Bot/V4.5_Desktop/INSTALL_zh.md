# V4.5 Desktop 安裝與啟動教學（繁體中文）

**最新版本**：`cursor/v45-desktop-intelligence-16b9`  
**含修復**：資料載入、K 線、AI 提問、1 秒分頁切換等

---

## 一、下載最新版本

### 方式 A：直接下載 ZIP（最簡單，推薦）

1. 用瀏覽器打開（直接點擊下載）：
   **https://github.com/kenchan0730/V3_Bot/archive/refs/heads/cursor/v45-desktop-intelligence-16b9.zip**
2. 解壓縮 ZIP
3. 進入資料夾：`V3_Bot-cursor-v45-desktop-intelligence-16b9\V4.5_Bot`

### 方式 B：Git 克隆（方便日後更新）

```cmd
git clone https://github.com/kenchan0730/V3_Bot.git
cd V3_Bot
git checkout cursor/v45-desktop-intelligence-16b9
cd V4.5_Bot
```

### 方式 C：查看更新說明（Pull Request）

**https://github.com/kenchan0730/V3_Bot/pull/5**

---

## 二、安裝前置軟體（只需做一次）

| 軟體 | 用途 | 下載 |
|------|------|------|
| **Python 3.11**（必須） | 後端 API | https://www.python.org/downloads/release/python-3119/ |
| **Node.js 18+** | 前端建置（首次） | https://nodejs.org/ |

安裝 Python 時請勾選：
- ✅ **Add Python to PATH**
- ✅ **Install launcher for all users (py launcher)**

安裝後在 **cmd** 測試：

```cmd
py -3.11 --version
node --version
```

應顯示 `Python 3.11.x` 和 `v18.x` 或以上。

---

## 三、第一次設定（約 5 分鐘，只做一次）

### 步驟 1：首次設定

1. 進入 `V4.5_Bot` 資料夾
2. **雙擊** `V4.5_Desktop\setup.bat`
3. 等待完成（安裝依賴 + 建置前端）

### 步驟 2：設定 API 金鑰（建議）

用記事本打開 `data\.env`，填入：

```env
FINNHUB_KEY=你的_Finnhub_金鑰
TOTAL_CAPITAL=1275.0
```

> Finnhub 免費註冊：https://finnhub.io/register  
> 用於：內部交易、財報日曆、股票搜尋。未設定時情報／技術面仍可用。

### 步驟 3：建立捷徑（推薦）

**雙擊** `V4.5_Desktop\create_shortcut.bat`

- 會在**桌面**建立「V4.5 Intelligence」捷徑
- 可選 **Y** → 加入**開機自動啟動**
- 若仍看不到捷徑，腳本會改在桌面建立 **「V4.5 Intelligence (雙擊啟動).bat」**

**手動建立捷徑（若腳本失敗）：**

1. 在桌面按右鍵 → **新增** → **捷徑**
2. 位置填入（改成你的實際路徑）：
   ```
   C:\Users\你的用戶名\Desktop\V3_Bot-cursor-v45-desktop-intelligence-16b9\V4.5_Bot\V4.5_Desktop\open.bat
   ```
3. 名稱：`V4.5 Intelligence`
4. 完成

> 桌面若在 **OneDrive**，捷徑會出現在 OneDrive 的 Desktop 資料夾，不是本機 Desktop。

---

## 四、每次開機 / 日常使用

### 🟢 方法一：桌面捷徑（最方便）

雙擊桌面 **「V4.5 Intelligence」** → 自動啟動 API + 開啟瀏覽器

### 🟢 方法二：直接雙擊 open.bat

路徑：`V4.5_Bot\V4.5_Desktop\open.bat`

### 🟢 方法三：開機自動啟動

若執行過 `create_shortcut.bat` 並選 **Y**，每次開機會自動：
1. 啟動後端 API（port 8765）
2. 約 4 秒後開啟瀏覽器

**取消開機啟動**：刪除以下檔案即可  
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\V4.5 Intelligence.lnk`

### 瀏覽器地址

**http://127.0.0.1:8765**

> 首次啟動後端會在背景預熱約 15–20 秒，之後各分頁約 1 秒內載入。

### 關閉程式

關閉標題為 **「V4.5 API」** 的黑色命令視窗即可。

---

## 五、更新到最新版

### 若用 ZIP 下載

1. 重新下載最新 ZIP（見上方連結）
2. 解壓到新資料夾（或覆蓋舊的 `V4.5_Bot`）
3. **保留** 舊的 `data\.env`（複製到新資料夾）
4. 雙擊 `setup.bat`（若前端有更新）
5. 雙擊 `open.bat` 或桌面捷徑

### 若用 Git

```cmd
cd V3_Bot
git pull origin cursor/v45-desktop-intelligence-16b9
cd V4.5_Bot\V4.5_Desktop\frontend
npm run build
cd ..\..
V4.5_Desktop\open.bat
```

---

## 六、介面導覽

| 按鈕 | 功能 |
|------|------|
| 情報 | 美股新聞、自選股、K 線 |
| 技術 | 市場環境、ETF、板塊、基本面 |
| 內部 | 內部交易（需 FINNHUB_KEY） |
| 日曆 | 財報日程 |
| AI | 問答 + 購買訊號 |
| 搜尋 | 搜股票、熱門趨勢 |

右上角：**分析模式 · 無自動交易**（不會自動下單）

---

## 七、常見問題

### 打不開網頁？

1. 確認「V4.5 API」視窗沒有報錯
2. 瀏覽器打開 http://127.0.0.1:8765/api/health  
   應看到：`{"status":"ok",...}`

### 資料全是 $0 或空白？

1. 確認使用 **Python 3.11**（`py -3.11 --version`）
2. 關閉舊的 8765 埠程序，重新執行 `open.bat`

### AI 提問報錯？

更新到最新版；一般提問（如 `aapl`）應 <1 秒回覆。

### 內部交易 / 財報日曆空白？

在 `data\.env` 設定 `FINNHUB_KEY` 後重啟。

---

有問題可到 GitHub PR #5 留言。
