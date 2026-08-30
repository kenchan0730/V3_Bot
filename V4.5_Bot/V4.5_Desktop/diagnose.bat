@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
set "ROOT=%CD%"
set "DESKTOP=%ROOT%\V4.5_Desktop"
set "PYTHONPATH=%ROOT%"

call "%DESKTOP%\_find_python.bat"
if errorlevel 1 exit /b 1

echo ========================================
echo   V4.5 Desktop Diagnostics
echo ========================================
echo.

%PY% "%DESKTOP%\scripts\verify_setup.py"
echo.
pause
exit /b %ERRORLEVEL%
