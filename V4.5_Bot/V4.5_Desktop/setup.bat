@echo off
REM V4.5 Desktop 首次設定（Windows）
setlocal
cd /d "%~dp0\.."
set ROOT=%CD%

echo ========================================
echo   V4.5 Desktop 首次設定
echo ========================================

python --version >nul 2>&1 || (
  echo [錯誤] 找不到 Python。請先安裝: https://www.python.org/downloads/
  echo 安裝時請勾選 "Add Python to PATH"
  pause
  exit /b 1
)

node --version >nul 2>&1 || (
  echo [警告] 找不到 Node.js。首次啟動需要 Node.js: https://nodejs.org/
)

echo.
echo [1/3] 安裝 Python 依賴...
python -m pip install -r requirements.txt
python -m pip install -r V4.5_Desktop\requirements.txt

echo.
echo [2/3] 建立設定檔 data\.env ...
if not exist "data\.env" (
  if exist "data\.env.example" (
    copy /Y "data\.env.example" "data\.env" >nul
    echo 已複製 data\.env.example -^> data\.env
    echo 請用記事本編輯 data\.env，填入 FINNHUB_KEY（可選）
  ) else (
    echo [警告] 找不到 data\.env.example
  )
) else (
  echo data\.env 已存在，略過
)

echo.
echo [3/3] 建置前端（首次約 1-2 分鐘）...
cd V4.5_Desktop\frontend
call npm install
call npm run build
cd /d "%ROOT%"

echo.
echo ========================================
echo   設定完成！
echo   下一步：雙擊 V4.5_Desktop\open.bat 啟動
echo   或執行: V4.5_Desktop\open.bat
echo ========================================
pause
