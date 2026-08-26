@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "OPEN_BAT=%~dp0open.bat"
set "WORKDIR=%~dp0"
if "%WORKDIR:~-1%"=="\" set "WORKDIR=%WORKDIR:~0,-1%"

set "DESKTOP=%USERPROFILE%\Desktop"
if exist "%USERPROFILE%\OneDrive\Desktop\" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"

set "LAUNCHER=%DESKTOP%\V4.5 Intelligence (Start).bat"

if not exist "%OPEN_BAT%" (
  echo [ERROR] open.bat not found
  pause
  exit /b 1
)

if not exist "%DESKTOP%" mkdir "%DESKTOP%" 2>nul

> "%LAUNCHER%" echo @echo off
>> "%LAUNCHER%" echo cd /d "%WORKDIR%"
>> "%LAUNCHER%" echo call "%OPEN_BAT%"

if exist "%LAUNCHER%" (
  echo [OK] Created:
  echo   %LAUNCHER%
  echo.
  echo Double-click this file to start V4.5.
) else (
  echo [ERROR] Failed to create launcher.
  echo Manually create a shortcut to:
  echo   %OPEN_BAT%
)

pause
exit /b 0
