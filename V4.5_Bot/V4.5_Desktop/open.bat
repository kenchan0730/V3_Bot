@echo off
REM V4.5 Desktop 一鍵啟動（Windows）— 需要 Python 3.11
setlocal EnableDelayedExpansion
cd /d "%~dp0\..\.."
set ROOT=%CD%
set DESKTOP=%ROOT%\V4.5_Desktop
set FRONTEND=%DESKTOP%\frontend
set PORT=8765
set URL=http://127.0.0.1:%PORT%
set PYTHONPATH=%ROOT%

REM --- 選定 Python 3.11 ---
set "PY="
where py >nul 2>&1 && (
  py -3.11 -c "import sys; assert sys.version_info[:2]==(3,11)" >nul 2>&1 && set "PY=py -3.11"
)
if not defined PY (
  where python3.11 >nul 2>&1 && set "PY=python3.11"
)
if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    "%%P" -c "import sys; exit(0 if sys.version_info[:2]==(3,11) else 1)" >nul 2>&1 && (
      set "PY=%%P"
      goto :found_py
    )
  )
)
:found_py
if not defined PY (
  echo.
  echo [錯誤] 找不到 Python 3.11
  echo.
  echo 請確認已安裝 Python 3.11 並勾選 "Add Python to PATH"
  echo 下載: https://www.python.org/downloads/release/python-3119/
  echo.
  echo 安裝後在 cmd 測試:  py -3.11 --version
  echo.
  pause
  exit /b 1
)

echo 使用: %PY%
%PY% --version

if not exist "%ROOT%\data\.env" (
  if exist "%ROOT%\data\.env.example" (
    copy /Y "%ROOT%\data\.env.example" "%ROOT%\data\.env" >nul
    echo 已建立 data\.env（可編輯填入 FINNHUB_KEY）
  )
)

echo ========================================
echo   V4.5 Intelligence Desktop
echo ========================================

%PY% -c "import fastapi, uvicorn, yfinance" 2>nul || (
  echo 安裝 Python 依賴（Python 3.11）...
  %PY% -m pip install --upgrade pip
  %PY% -m pip install -r requirements.txt
  %PY% -m pip install -r V4.5_Desktop\requirements.txt
)

if not exist "%FRONTEND%\dist" (
  where npm >nul 2>&1 || (
    echo [錯誤] 找不到 npm。請安裝 Node.js: https://nodejs.org/
    pause
    exit /b 1
  )
  echo 建置前端（首次約 1-2 分鐘）...
  cd /d "%FRONTEND%"
  call npm install
  call npm run build
  cd /d "%ROOT%"
)

echo 啟動 API: %URL%
cd /d "%DESKTOP%\backend"
start "V4.5 API" cmd /k "%PY% -m uvicorn app:app --host 127.0.0.1 --port %PORT%"

timeout /t 4 /nobreak >nul
start "" %URL%

echo.
echo 已啟動。關閉「V4.5 API」黑色視窗即可停止。
echo 瀏覽器: %URL%
pause
