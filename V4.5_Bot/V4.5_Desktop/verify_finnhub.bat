@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
set "ROOT=%CD%"
set "PYTHONPATH=%ROOT%"

call "%~dp0\_find_python.bat"
if errorlevel 1 exit /b 1

echo ========================================
echo   Finnhub Key Test
echo ========================================
echo.

%PY% -c "import os; from pathlib import Path; p=Path('data/.env'); print('data/.env exists:', p.exists()); k=os.environ.get('FINNHUB_KEY') or os.environ.get('FINNHUB_API_KEY'); print('FINNHUB_KEY set:', bool(k)); print('Key prefix:', (k or '')[:8])"

echo.
echo Testing AAPL quote...
%PY% -c "import sys; sys.path.insert(0,'V4.5_Desktop/backend'); from core.config_loader import load_dotenv; load_dotenv('data/.env'); from services.market_cache import quote_one; q=quote_one('AAPL'); print('AAPL:', q); print('OK' if q.get('price',0)>0 else 'FAILED - fix FINNHUB_KEY in data/.env')"

echo.
pause
