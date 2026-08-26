@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "OPEN_BAT=%~dp0open.bat"
set "WORKDIR=%~dp0"
if "%WORKDIR:~-1%"=="\" set "WORKDIR=%WORKDIR:~0,-1%"

echo ========================================
echo   V4.5 Intelligence - Create Shortcut
echo ========================================
echo.

if not exist "%OPEN_BAT%" (
  echo [ERROR] Cannot find open.bat
  echo Path: %OPEN_BAT%
  pause
  exit /b 1
)

where cscript >nul 2>&1
if errorlevel 1 (
  echo [ERROR] cscript not found. Windows Script Host is required.
  goto FALLBACK
)

echo Target: %OPEN_BAT%
echo.

cscript //nologo "%~dp0create_shortcut.vbs" "%OPEN_BAT%" "%WORKDIR%" desktop
if errorlevel 1 goto FALLBACK

echo.
set /p STARTUP=Add to Windows Startup on boot? (Y/N): 
if /i "%STARTUP%"=="Y" (
  cscript //nologo "%~dp0create_shortcut.vbs" "%OPEN_BAT%" "%WORKDIR%" startup
  if errorlevel 1 (
    echo [WARN] Startup shortcut failed. Use FALLBACK if needed.
  )
)

echo.
echo Done. Double-click "V4.5 Intelligence" on your Desktop.
echo Browser: http://127.0.0.1:8765
echo.
pause
exit /b 0

:FALLBACK
echo.
echo Creating fallback launcher on Desktop...
call "%~dp0install_desktop_launcher.bat"
exit /b %ERRORLEVEL%
