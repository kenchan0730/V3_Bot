@echo off
set "PY="
py -3.11 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3.11" & exit /b 0
python3.11 --version >nul 2>&1
if not errorlevel 1 set "PY=python3.11" & exit /b 0
python --version 2>nul | findstr "3.11" >nul 2>&1
if not errorlevel 1 set "PY=python" & exit /b 0
echo ERROR: Python 3.11 not found.
echo Install: https://www.python.org/downloads/release/python-3119/
echo Then run: py -3.11 --version
pause
exit /b 1
