@echo off
REM V4.5 Desktop 一鍵啟動（Windows）
setlocal
cd /d "%~dp0\..\.."
set ROOT=%CD%
set DESKTOP=%ROOT%\V4.5_Desktop
set FRONTEND=%DESKTOP%\frontend
set PORT=8765
set URL=http://127.0.0.1:%PORT%
set PYTHONPATH=%ROOT%

echo ========================================
echo   V4.5 Intelligence Desktop
echo ========================================

python --version >nul 2>&1 || (
  echo 請先安裝 Python 3.10+: https://www.python.org/downloads/
  exit /b 1
)

python -c "import fastapi, uvicorn, yfinance" 2>nul || (
  echo 安裝 Python 依賴...
  python -m pip install -r requirements.txt -q
  python -m pip install -r V4.5_Desktop\requirements.txt -q
)

if not exist "%FRONTEND%\dist" (
  echo 建置前端（首次約 1-2 分鐘）...
  cd /d "%FRONTEND%"
  call npm install
  call npm run build
  cd /d "%ROOT%"
)

echo 啟動 API: %URL%
cd /d "%DESKTOP%\backend"
start "V4.5 API" python -m uvicorn app:app --host 127.0.0.1 --port %PORT%

timeout /t 3 /nobreak >nul
start %URL%

echo.
echo 已啟動。關閉 V4.5 API 視窗即可停止服務。
echo 瀏覽器: %URL%
pause
