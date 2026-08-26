@echo off
REM V4.5 Desktop 首次設定（Windows）— 需要 Python 3.11
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."
set ROOT=%CD%

set "PY="
where py >nul 2>&1 && (
  py -3.11 -c "import sys; assert sys.version_info[:2]==(3,11)" >nul 2>&1 && set "PY=py -3.11"
)
if not defined PY (
  where python3.11 >nul 2>&1 && set "PY=python3.11"
)
if not defined PY (
  echo [錯誤] 找不到 Python 3.11
  echo 請安裝: https://www.python.org/downloads/release/python-3119/
  echo 安裝後測試: py -3.11 --version
  pause
  exit /b 1
)

echo ========================================
echo   V4.5 Desktop 首次設定
echo   使用: %PY%
echo ========================================
%PY% --version

node --version >nul 2>&1 || (
  echo [警告] 找不到 Node.js。建置前端需要: https://nodejs.org/
)

echo.
echo [1/3] 安裝 Python 依賴...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
%PY% -m pip install -r V4.5_Desktop\requirements.txt

echo.
echo [2/3] 建立設定檔 data\.env ...
if not exist "data\.env" (
  if exist "data\.env.example" (
    copy /Y "data\.env.example" "data\.env" >nul
    echo 已複製 data\.env.example -^> data\.env
    echo 請用記事本編輯 data\.env，填入 FINNHUB_KEY（可選）
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
echo   設定完成！雙擊 V4.5_Desktop\open.bat 啟動
echo ========================================
pause
