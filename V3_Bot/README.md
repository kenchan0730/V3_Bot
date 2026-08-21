# V4.5 Trading Bot (`V3_Bot`)

Automated US equities trading system with quantitative scoring, candle-pattern signals, market-breadth gating, and optional IBKR execution.

## Architecture

```
main.py                 # Trading loop (IBKR + yfinance, risk gates, signals)
app.py                  # Streamlit dashboard (live metrics)
config.yaml             # Capital, risk, watchlist, integrations

core/
  data_utils.py         # normalize_columns() — unified OHLCV column names
  quant_engine.py       # Z-Score, RSI, momentum/volume/volatility scoring
  candle_patterns.py    # Hammer, engulfing, morning star, etc.
  trading_signals.py    # Combined technical + candle signal logic
  risk_manager.py       # Position sizing, VIX, drawdown, daily loss limits
  emotion_manager.py    # Trade-frequency / loss-streak guardrails
  market_breadth.py     # External CSV breadth score + exposure tiers
  sector_tracker.py     # Sector relative strength (exposure adjustment)
  fundamental_filter.py # yfinance fundamentals pre-filter
  notifier.py             # Telegram trade alerts (optional)
  ibkr_connector.py     # Interactive Brokers data + orders

archive/                # Modules not in main loop (scanner, news sentiment)
tests/                  # pytest unit tests
```

## Data flow

1. Load config and optional `logs/state.json`.
2. Connect IBKR (fallback: yfinance).
3. Gate on market hours, drawdown, daily loss, and market breadth.
4. For each watchlist symbol: fundamental filter → fetch OHLCV → `normalize_columns`.
5. `QuantEngine.dynamic_score` → structure/volume filters → `TradingSignals`.
6. Size positions via `RiskManager` with breadth + sector exposure scaling.
7. Optional auto-trade via IBKR; optional Telegram notifications.

## Setup

```bash
cd V3_Bot
pip install -r requirements.txt
```

Configure `config.yaml` (IBKR host/port, watchlist, risk limits). For Telegram alerts, set `notifier.enabled` and bot credentials.

## Run

**Trading bot (signal / auto-trade):**

```bash
python main.py
```

Stop with `Ctrl+C` — state is saved to `logs/state.json` and IBKR disconnects gracefully.

**Dashboard:**

```bash
streamlit run app.py
```

**Tests:**

```bash
pytest --cov=core --cov-report=term-missing
```

**Diagnostics:**

```bash
python test_setup.py
python test_breadth.py
```

## Requirements

- Python 3.10+
- IBKR TWS/Gateway for live IB data and orders (optional)
- Network access for yfinance and market-breadth CSV sources

## Notes

- Project folder remains `V3_Bot`; runtime version is V4.5.
- `archive/stock_scanner.py` and `archive/news_sentiment.py` are documented in `archive/README.md`.
- Candle patterns require lowercase OHLCV columns; normalization is applied at fetch time and in core entry points.
