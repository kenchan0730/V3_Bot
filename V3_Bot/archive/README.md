# Archived Modules

These modules are not wired into the main trading loop yet. They remain available for future integration.

## `stock_scanner.py`

- Scans S&P 500 constituents via Wikipedia + yfinance prefilter.
- **Status:** Functional but slow for real-time loops; use offline to build watchlists instead of scanning inside `main.py`.
- **Dependencies:** `yfinance`, `pandas`, `lxml` (for `pd.read_html`).

## `news_sentiment.py`

- Finnhub news headline sentiment scoring.
- **Status:** Requires a Finnhub API key (`news.finnhub_key` in config). Disabled by default in `config.yaml`.
- **Dependencies:** `finnhub-python`.

To use either module, copy back to `core/` or import from `archive` explicitly after configuring credentials and testing offline.
