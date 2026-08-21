# Archived Modules

Modules kept for reference but intentionally excluded from the live trading loop.

## `stock_scanner.py`

- Scans S&P 500 constituents via Wikipedia + a yfinance prefilter.
- **Status:** Functional but network-heavy and slow; unsuitable for the 5-minute
  scan cadence. Intended for **offline watchlist construction**, not the live loop.
- **Dependencies:** `yfinance`, `pandas`, `lxml` (for `pd.read_html`).
- **How to use:** run it as a standalone script and paste the resulting symbols
  into `watchlist` in `config.yaml`.

## Previously archived, now integrated

- `news_sentiment.py` was moved back to `core/` and is wired as an optional
  sentiment gate. It stays disabled until `FINNHUB_KEY` is present in `.env`
  and `news.enabled: true` is set in `config.yaml`.
