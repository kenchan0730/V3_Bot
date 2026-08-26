# V4.5 Desktop 安裝與啟動教學（繁體中文）

**最新版本**：`cursor/v45-desktop-intelligence-16b9`  
**提交**：含效能優化與 bug 修復（批次報價、快取、內部交易 500 修復等）

---

## 一、下載最新版本

### 方式 A：Git 克隆（推薦，日後可更新）

```bash
git clone https://github.com/kenchan0730/V3_Bot.git
cd V3_Bot
git checkout cursor/v45-desktop-intelligence-16b9
```

### 方式 B：直接下載 ZIP（不用 Git）

1. 打開瀏覽器，前往：
   **https://github.com/kenchan0730/V3_Bot/archive/refs/heads/cursor/v45-desktop-intelligence-16b9.zip**
2. 下載 ZIP 並解壓縮
3. 進入資料夾：`V3_Bot-cursor-v45-desktop-intelligence-16b9/V4.5_Bot`

### 方式 C：Pull Request（可查看變更說明）

**https://github.com/kenchan0730/V3_Bot/pull/5**

---

## 二、安裝前置軟體

| 軟體 | 用途 | 下載 |
|------|------|------|
| **Python 3.10+** | 後端 API | https://www.python.org/downloads/ |
| **Node.js 18+** | 前端建置（首次） | https://nodejs.org/ |

安裝後在終端機確認：

```bash
python3 --version    # 或 Windows: python --version
node --version
npm --version
```

---

## 三、第一次設定（約 5 分鐘）

### 🪟 Windows 用戶（請看這段）

在 **命令提示字元（cmd）** 或 **PowerShell** 中操作（不要用 Mac/Linux 的 `cp` 指令）。

**一鍵首次設定（推薦）**

1. 進入 `V4.5_Bot` 資料夾（ZIP 解壓後的路徑）
2. **雙擊** `V4.5_Desktop\setup.bat`
3. 完成後 **雙擊** `V4.5_Desktop\open.bat`

**手動設定（命令提示字元 cmd）**

```cmd
cd 你的路徑\V4.5_Bot

python -m pip install -r requirements.txt
python -m pip install -r V4.5_Desktop\requirements.txt

copy data\.env.example data\.env

notepad data\.env
```

在記事本填入（Finnhub 可選）：

```env
FINNHUB_KEY=你的金鑰
TOTAL_CAPITAL=1275.0
```

儲存後雙擊 `V4.5_Desktop\open.bat` 啟動。

---

### Mac / Linux 用戶

### 步驟 1：進入專案目錄

```bash
cd V3_Bot/V4.5_Bot
```

（若用 ZIP，路徑類似 `V3_Bot-cursor-v45-desktop-intelligence-16b9/V4.5_Bot`）

### 步驟 2：安裝 Python 依賴

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -r V4.5_Desktop/requirements.txt
```

Windows 若 `python3` 無效，改用 `python`。

### 步驟 3：（可選）設定 API 金鑰

**Mac / Linux** 複製環境變數範本：

```bash
cp data/.env.example data/.env
```

**Windows** 請用：

```cmd
copy data\.env.example data\.env
notepad data\.env
```

編輯 `data/.env`，填入（可選，但建議）：

```env
FINNHUB_KEY=你的_Finnhub_金鑰
TOTAL_CAPITAL=1275.0
```

> **Finnhub 免費註冊**：https://finnhub.io/register  
> 用於：內部交易、財報日曆、股票搜尋。未設定時情報／技術面仍可用。

---

## 四、打開應用程式

### 🟢 最簡單：一鍵啟動

**Windows**：雙擊 `V4.5_Desktop\open.bat`（首次請先雙擊 `setup.bat`）

**Mac / Linux**：

```bash
cd V4.5_Bot
chmod +x V4.5_Desktop/open.sh
./V4.5_Desktop/open.sh
```

腳本會自動：
1. 安裝缺少的依賴
2. 首次建置前端
3. 啟動 API（port **8765**）
4. 開啟瀏覽器

**瀏覽器地址**：http://127.0.0.1:8765

---

### 手動啟動（適合 Windows 或想分開除錯）

需要開 **兩個終端機**。

#### 終端機 1 — 後端 API

```bash
cd V4.5_Bot
export PYTHONPATH=$(pwd)          # Windows PowerShell: $env:PYTHONPATH = (Get-Location)
cd V4.5_Desktop/backend
python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

看到 `Uvicorn running on http://127.0.0.1:8765` 即成功。

#### 終端機 2 — 前端（開發模式）

```bash
cd V4.5_Bot/V4.5_Desktop/frontend
npm install
npm run dev
```

瀏覽器打開：**http://127.0.0.1:5173**

---

### 單一端口（建置後只開 8765）

```bash
cd V4.5_Bot/V4.5_Desktop/frontend
npm install
npm run build
cd ../../V4.5_Desktop/backend
python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

瀏覽器：**http://127.0.0.1:8765**

---

## 五、介面導覽

底部六個按鈕：

| 按鈕 | 功能 |
|------|------|
| 情報 | 美股新聞評分、自選股、K 線／新聞／財報 |
| 技術 | 市場環境分數、ETF、板塊、頭條、基本面 |
| 內部 | 內部交易日曆與排名 |
| 日曆 | 財報日程與評分 |
| AI | 問答 + 購買訊號提醒 |
| 搜尋 | 搜股票、熱門趨勢 |

右上角標示 **「分析模式 · 無自動交易」** — 不會自動下單。

---

## 六、常見問題

### 打不開網頁？

1. 確認終端機沒有報錯
2. 手動訪問 http://127.0.0.1:8765/api/health  
   應看到：`{"status":"ok","mode":"intelligence-only",...}`

### 內部交易沒有數據？

設定 `FINNHUB_KEY` 或 `FINNHUB_API_KEY` 於 `data/.env`，重啟 API。

### AI 信號第一次很慢？

正常。首次分析約 1 分鐘，之後有快取（約 5 分鐘內即時）。

### 關閉程式

- 手動啟動：在終端機按 `Ctrl + C`
- 一鍵腳本：`kill $(cat /tmp/v45-desktop.pid)`

---

## 七、更新到最新版

若用 Git 克隆：

```bash
cd V3_Bot
git pull origin cursor/v45-desktop-intelligence-16b9
cd V4.5_Bot
rm -rf V4.5_Desktop/frontend/dist
./V4.5_Desktop/open.sh
```

---

有問題可到 GitHub Issues 或 PR #5 留言。
