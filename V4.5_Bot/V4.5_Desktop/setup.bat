@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
set "ROOT=%CD%"
set "DESKTOP=%ROOT%\V4.5_Desktop"
set "FRONTEND=%DESKTOP%\frontend"

call "%DESKTOP%\_find_python.bat"
if errorlevel 1 exit /b 1

echo ========================================
echo   V4.5 Desktop Setup
echo   Using: %PY%
echo ========================================
%PY% --version

node --version >nul 2>&1
if errorlevel 1 (
  echo WARN: Node.js not found. Need it for frontend: https://nodejs.org/
)

echo.
echo [1/3] Installing Python packages...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r "%ROOT%\requirements.txt"
%PY% -m pip install -r "%DESKTOP%\requirements.txt"

echo.
echo [2/3] Creating data\.env ...
if not exist "%ROOT%\data\.env" (
  if exist "%ROOT%\data\.env.example" (
    copy /Y "%ROOT%\data\.env.example" "%ROOT%\data\.env" >nul
    echo Copied data\.env.example to data\.env
    echo Edit data\.env and add FINNHUB_KEY optional
  )
) else (
  echo data\.env already exists - skipped
)

echo.
echo [3/3] Building frontend - 1-2 min...
cd /d "%FRONTEND%"
call npm install
if errorlevel 1 goto SETUP_FAIL
call npm run build
if errorlevel 1 goto SETUP_FAIL
cd /d "%ROOT%"

echo.
echo ========================================
echo   SETUP DONE - run V4.5_Desktop\open.bat
echo ========================================
pause
exit /b 0

:SETUP_FAIL
echo.
echo ERROR: setup failed - check messages above
pause
exit /b 1
