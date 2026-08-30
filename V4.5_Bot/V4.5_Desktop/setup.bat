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
  echo [FAIL] Node.js not found - install from https://nodejs.org/
  echo        Frontend build cannot run without Node.js.
  pause
  exit /b 1
)

echo.
echo [1/3] Installing Python packages (desktop only)...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r "%DESKTOP%\requirements.txt"
if errorlevel 1 (
  echo [FAIL] pip install failed - see errors above
  goto SETUP_FAIL
)

echo.
echo [2/3] Creating data\.env ...
if not exist "%ROOT%\data\.env" (
  if exist "%ROOT%\data\.env.example" (
    copy /Y "%ROOT%\data\.env.example" "%ROOT%\data\.env" >nul
    echo Copied data\.env.example to data\.env
    echo Edit data\.env and add FINNHUB_KEY
  ) else (
    echo [WARN] data\.env.example missing
  )
) else (
  echo data\.env already exists - skipped
)

echo.
echo [3/3] Building frontend - 1-2 min...
cd /d "%FRONTEND%"
if exist tsconfig.tsbuildinfo del /q tsconfig.tsbuildinfo
call npm install
if errorlevel 1 (
  echo [FAIL] npm install failed
  goto SETUP_FAIL
)
call npm run build
if errorlevel 1 (
  echo [FAIL] npm run build failed - if you see TypeScript errors above, screenshot them
  goto SETUP_FAIL
)
cd /d "%ROOT%"

echo.
echo Running diagnostics...
set "PYTHONPATH=%ROOT%"
%PY% "%DESKTOP%\scripts\verify_setup.py"
set "DIAG=%ERRORLEVEL%"

echo.
if "%DIAG%"=="0" (
  echo ========================================
  echo   SETUP DONE - run V4.5_Desktop\open.bat
  echo ========================================
) else (
  echo ========================================
  echo   SETUP FINISHED WITH ERRORS
  echo   Fix [FAIL] items above, then open.bat
  echo ========================================
)
pause
exit /b %DIAG%

:SETUP_FAIL
echo.
echo ERROR: setup failed - fix the [FAIL] lines above before open.bat
pause
exit /b 1
