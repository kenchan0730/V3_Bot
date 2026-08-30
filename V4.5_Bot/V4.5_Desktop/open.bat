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
    echo Created data\.env - add FINNHUB_KEY then restart
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
%PY% -m pip install -r "%DESKTOP%\requirements.txt"
if errorlevel 1 (
  echo ERROR: pip install failed - run setup.bat first
  pause
  exit /b 1
)

:DEPS_OK

if exist "%FRONTEND%\dist\index.html" goto FRONTEND_OK

where npm >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm not found. Run setup.bat after installing Node.js
  pause
  exit /b 1
)

echo Building frontend - first time 1-2 min...
cd /d "%FRONTEND%"
if exist tsconfig.tsbuildinfo del /q tsconfig.tsbuildinfo
call npm install
if errorlevel 1 goto BUILD_FAIL
call npm run build
if errorlevel 1 goto BUILD_FAIL
cd /d "%ROOT%"
goto FRONTEND_OK

:BUILD_FAIL
echo ERROR: frontend build failed - run setup.bat and check TypeScript errors
pause
exit /b 1

:FRONTEND_OK
echo Starting API: %URL%
cd /d "%DESKTOP%\backend"
start "V4.5 API" cmd /k "%PY% -m uvicorn app:app --host 127.0.0.1 --port %PORT%"

echo Waiting for API to start...
set /a WAIT_COUNT=0
:WAIT_API
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%URL%/api/health' -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto API_OK
set /a WAIT_COUNT+=1
if %WAIT_COUNT% LSS 20 goto WAIT_API
echo.
echo ERROR: API did not respond on %URL%
echo Check the "V4.5 API" window for Python errors.
echo Run: %DESKTOP%\diagnose.bat
pause
exit /b 1

:API_OK
echo API is ready.
start "" "%URL%"

echo.
echo Started. Close the V4.5 API window to stop.
echo Browser: %URL%
echo If pages show errors, run: %DESKTOP%\diagnose.bat
pause
exit /b 0
