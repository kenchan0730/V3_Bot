@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
set "ROOT=%CD%"
set "DESKTOP=%ROOT%\V4.5_Desktop"
set "FRONTEND=%DESKTOP%\frontend"
set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%"
set "PYTHONPATH=%ROOT%"

call "%DESKTOP%\_find_python.bat"
if errorlevel 1 exit /b 1

echo Using: %PY%
%PY% --version

if not exist "%ROOT%\data\.env" (
  if exist "%ROOT%\data\.env.example" (
    copy /Y "%ROOT%\data\.env.example" "%ROOT%\data\.env" >nul
    echo Created data\.env - edit FINNHUB_KEY optional
  )
)

echo ========================================
echo   V4.5 Intelligence Desktop
echo ========================================

%PY% -c "import fastapi, uvicorn, yfinance" >nul 2>&1
if errorlevel 1 goto INSTALL_DEPS
goto DEPS_OK

:INSTALL_DEPS
echo Installing Python packages...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r "%ROOT%\requirements.txt"
%PY% -m pip install -r "%DESKTOP%\requirements.txt"

:DEPS_OK

if exist "%FRONTEND%\dist\index.html" goto FRONTEND_OK

where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm not found. Install Node.js from https://nodejs.org/
  pause
  exit /b 1
)

echo Building frontend - first time 1-2 min...
cd /d "%FRONTEND%"
call npm install
if errorlevel 1 goto BUILD_FAIL
call npm run build
if errorlevel 1 goto BUILD_FAIL
cd /d "%ROOT%"
goto FRONTEND_OK

:BUILD_FAIL
echo ERROR: frontend build failed
pause
exit /b 1

:FRONTEND_OK
echo Starting API: %URL%
cd /d "%DESKTOP%\backend"
start "V4.5 API" cmd /k "%PY% -m uvicorn app:app --host 127.0.0.1 --port %PORT%"

timeout /t 4 /nobreak >nul
start "" "%URL%"

echo.
echo Started. Close the V4.5 API window to stop.
echo Browser: %URL%
pause
exit /b 0
