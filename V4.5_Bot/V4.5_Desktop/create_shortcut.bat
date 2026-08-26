@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM 去掉結尾反斜線（避免 VBS/PowerShell 路徑錯誤）
set "OPEN_BAT=%~dp0open.bat"
set "WORKDIR=%~dp0"
if "%WORKDIR:~-1%"=="\" set "WORKDIR=%WORKDIR:~0,-1%"

set "LINK_NAME=V4.5 Intelligence.lnk"
set "VBS=%TEMP%\v45_create_shortcut.vbs"

echo ========================================
echo   建立 V4.5 Intelligence 捷徑
echo ========================================
echo.

if not exist "%OPEN_BAT%" (
  echo [錯誤] 找不到 open.bat
  echo 預期位置: %OPEN_BAT%
  echo.
  echo 請確認你在 V4.5_Desktop 資料夾內執行此腳本。
  pause
  exit /b 1
)

echo 啟動檔: %OPEN_BAT%
echo 工作目錄: %WORKDIR%
echo.

REM --- 用 VBS 建立捷徑（支援 OneDrive 桌面）---
(
echo Set ws = CreateObject^("WScript.Shell"^)
echo desktop = ws.SpecialFolders^("Desktop"^)
echo startup = ws.SpecialFolders^("Startup"^)
echo linkDesktop = desktop ^& "\V4.5 Intelligence.lnk"
echo linkStartup = startup ^& "\V4.5 Intelligence.lnk"
echo Set sc = ws.CreateShortcut^(linkDesktop^)
echo sc.TargetPath = "%OPEN_BAT%"
echo sc.WorkingDirectory = "%WORKDIR%"
echo sc.WindowStyle = 1
echo sc.Description = "V4.5 Intelligence"
echo sc.Save
echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
echo If fso.FileExists^(linkDesktop^) Then
echo   WScript.Echo "OK_DESKTOP=" ^& linkDesktop
echo Else
echo   WScript.Echo "FAIL_DESKTOP"
echo   WScript.Quit 1
echo End If
) > "%VBS%"

echo 正在建立桌面捷徑...
set "DESKTOP_LINK="
for /f "tokens=1,* delims==" %%A in ('cscript //nologo "%VBS%" 2^>^&1') do (
  if /i "%%A"=="OK_DESKTOP" set "DESKTOP_LINK=%%B"
)
set "VBS_ERR=%ERRORLEVEL%"
del "%VBS%" 2>nul

if defined DESKTOP_LINK (
  echo.
  echo [成功] 桌面捷徑已建立:
  echo   !DESKTOP_LINK!
  goto :ask_startup
)

echo.
echo [警告] VBS 建立捷徑失敗 ^(錯誤碼 %VBS_ERR%^)，改用備用方案...
call :create_fallback
if errorlevel 1 (
  echo.
  echo [失敗] 無法建立任何捷徑。請手動建立:
  echo   1. 在桌面按右鍵 -^> 新增 -^> 捷徑
  echo   2. 位置填入: %OPEN_BAT%
  echo   3. 名稱: V4.5 Intelligence
  pause
  exit /b 1
)
goto :ask_startup

:create_fallback
REM 備用：在桌面放一個 .bat 啟動檔
set "DESKTOP_DIR="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP_DIR=%%D"
if not defined DESKTOP_DIR set "DESKTOP_DIR=%USERPROFILE%\Desktop"
if not exist "%DESKTOP_DIR%" mkdir "%DESKTOP_DIR%" 2>nul

set "FALLBACK=%DESKTOP_DIR%\V4.5 Intelligence (雙擊啟動).bat"
(
echo @echo off
echo cd /d "%WORKDIR%"
echo call "%OPEN_BAT%"
) > "%FALLBACK%"

if exist "%FALLBACK%" (
  echo [成功] 備用啟動檔已建立:
  echo   %FALLBACK%
  exit /b 0
)
exit /b 1

:ask_startup
echo.
set "STARTUP_CHOICE="
set /p STARTUP_CHOICE=是否開機自動啟動 V4.5？(Y/N): 

if /i not "!STARTUP_CHOICE!"=="Y" (
  echo 略過開機啟動。
  goto :done
)

(
echo Set ws = CreateObject^("WScript.Shell"^)
echo startup = ws.SpecialFolders^("Startup"^)
echo linkStartup = startup ^& "\V4.5 Intelligence.lnk"
echo Set sc = ws.CreateShortcut^(linkStartup^)
echo sc.TargetPath = "%OPEN_BAT%"
echo sc.WorkingDirectory = "%WORKDIR%"
echo sc.WindowStyle = 1
echo sc.Description = "V4.5 Intelligence"
echo sc.Save
echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
echo If fso.FileExists^(linkStartup^) Then
echo   WScript.Echo "OK_STARTUP=" ^& linkStartup
echo Else
echo   WScript.Echo "FAIL_STARTUP"
echo End If
) > "%VBS%"

for /f "tokens=1,* delims==" %%A in ('cscript //nologo "%VBS%" 2^>^&1') do (
  if /i "%%A"=="OK_STARTUP" set "STARTUP_LINK=%%B"
)
del "%VBS%" 2>nul

if defined STARTUP_LINK (
  echo [成功] 已加入開機啟動:
  echo   !STARTUP_LINK!
) else (
  set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
  set "STARTUP_BAT=%STARTUP_DIR%\V4.5 Intelligence (開機啟動).bat"
  (
  echo @echo off
  echo cd /d "%WORKDIR%"
  echo call "%OPEN_BAT%"
  ) > "!STARTUP_BAT!"
  echo [成功] 備用開機啟動檔:
  echo   !STARTUP_BAT!
)

:done
echo.
echo ========================================
echo   完成！
echo   瀏覽器: http://127.0.0.1:8765
echo ========================================
echo.
echo 若桌面仍看不到圖示，請檢查:
echo   - OneDrive 桌面資料夾
echo   - 或搜尋「V4.5 Intelligence」
echo.
pause
exit /b 0
