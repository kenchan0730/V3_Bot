@echo off
REM 建立 V4.5 Intelligence 桌面捷徑 + 可選開機自動啟動
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "OPEN_BAT=%~dp0open.bat"
set "DESKTOP=%USERPROFILE%\Desktop"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LINK_NAME=V4.5 Intelligence.lnk"

echo ========================================
echo   建立 V4.5 Intelligence 捷徑
echo ========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$s = $ws.CreateShortcut('%DESKTOP%\%LINK_NAME%'); " ^
  "$s.TargetPath = '%OPEN_BAT%'; " ^
  "$s.WorkingDirectory = '%~dp0'; " ^
  "$s.Description = 'V4.5 Intelligence 分析桌面'; " ^
  "$s.WindowStyle = 1; " ^
  "$s.Save(); " ^
  "Write-Host '已建立桌面捷徑:' '%DESKTOP%\%LINK_NAME%'"

echo.
set /p STARTUP_CHOICE=是否開機自動啟動 V4.5？(Y/N): 
if /i "%STARTUP_CHOICE%"=="Y" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$s = $ws.CreateShortcut('%STARTUP%\%LINK_NAME%'); " ^
    "$s.TargetPath = '%OPEN_BAT%'; " ^
    "$s.WorkingDirectory = '%~dp0'; " ^
    "$s.Description = 'V4.5 Intelligence 開機啟動'; " ^
    "$s.WindowStyle = 1; " ^
    "$s.Save(); " ^
    "Write-Host '已加入開機啟動:' '%STARTUP%\%LINK_NAME%'"
  echo.
  echo 下次開機會自動啟動 API 並開啟瀏覽器。
) else (
  echo 略過開機啟動。你可隨時雙擊桌面捷徑手動開啟。
)

echo.
echo 完成！雙擊桌面「V4.5 Intelligence」即可使用。
echo 瀏覽器地址: http://127.0.0.1:8765
echo.
pause
