# V4.5 Trading Bot

Automated US equities trading system: quantitative scoring, candlestick pattern
signals, market-breadth gating, portfolio-level risk control, and optional
Interactive Brokers execution with broker-side protective stops.

> **Safety default:** `auto_trade` is `false`. The system produces signals and
> alerts until you complete the go-live checklist in [`RUNBOOK.md`](RUNBOOK.md).

---

## Architecture

```
main.py                   # TradingBot orchestrator: gates, scan loop, execution
app.py                    # Streamlit entry point (navigation)
dashboard.py              # Dashboard: bot state, P&L, positions, signals, blotter
config.yaml               # All settings; supports ${ENV_VAR} expansion
.env                      # Secrets (gitignored; see .env.example)

core/
  config_loader.py        # YAML + .env loading with ${VAR} expansion
  logging_setup.py        # Rotating file + console logging
  trading_state.py        # Capital, counters, realised P&L ledger, persistence
  data_utils.py           # Column normalisation + data quality gates
  quant_engine.py         # Z-Score, RSI, momentum/volume/volatility scoring
  candle_patterns.py      # Hammer, engulfing, doji, morning/evening star
  trading_signals.py      # Combined technical + candle signal
  strategies/             # Plugin interface (BaseStrategy) + v45_core
  risk_manager.py         # Sizing, VIX, drawdown, daily loss (all config-driven)
  portfolio.py            # Gross exposure, position count, sector, correlation
  emotion_manager.py      # Trade-frequency and loss-streak guardrails
  order_manager.py        # Order lifecycle, partial fills, timeout cancellation
  blotter.py              # Append-only CSV audit trail
  ibkr_connector.py       # IBKR data, bracket orders, reconciliation
  notifier.py             # Throttled Telegram/email operator alerts
  market_breadth.py       # External breadth score and exposure tiers
  sector_tracker.py       # Sector relative strength vs SPY
  fundamental_filter.py   # yfinance fundamentals gate (24h TTL cache)
  news_sentiment.py       # Optional Finnhub sentiment gate
  correlation.py          # Weekly-returns correlation matrix

backtest/                 # Replays history through live strategy + risk code
tests/                    # 305 pytest cases
archive/                  # Modules intentionally out of the live loop
logs/                     # trading.log, state.json, trade_blotter.csv
```

---

## Trading loop

1. Roll daily counters; reload persisted state.
2. Gate on market hours (US Eastern), drawdown, daily loss, and book limits.
3. Refresh VIX; refresh market breadth and sector exposure hourly.
4. Reconcile with IBKR: positions, net liquidation, realised P&L from fills.
5. Poll tracked orders; cancel any that exceeded the timeout.
6. Per symbol: fundamentals → optional news → fetch data → quality gates
   (structure, freshness, outliers) → `QuantEngine` → strategy prefilter → signal.
7. **Buy:** size via `RiskManager`, scale by exposure and correlation, run
   pre-trade validation, then submit a **bracket order** (entry + stop + target).
8. **Sell:** cancel working orders, then flatten the actual broker position.
9. Write the blotter row, publish state, alert the operator.

### Risk controls

| Layer | Control |
|-------|---------|
| Per trade | Risk % of capital, stop distance sizing, price cap, max shares |
| Position | Single-name concentration cap, no duplicate entries |
| Sector | Per-sector exposure cap |
| Book | Gross exposure, max open positions, total open risk |
| Account | Daily loss limit, peak drawdown, absolute loss from initial |
| Market | Breadth halt below 20, stricter Z-Score floor below 40, VIX risk cap |
| Behaviour | Max daily trades, loss-streak risk reduction |
| Execution | Broker-side stops; entry aborted if the bracket cannot be placed |

---

## Setup

```bash
cd V3_Bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # fill in credentials
python test_setup.py      # dependency check
pytest -q                 # 305 tests
```

Secrets live in `.env` and are referenced from `config.yaml` as `${VAR}` or
`${VAR:-default}`. Requires Python 3.10+.

---

## Running

```bash
python main.py                  # per config.yaml (signal-only by default)
python main.py --dry-run        # never place orders
python main.py --once           # single scan, ignore market hours
streamlit run app.py            # dashboard on :8501
python -m backtest --symbols AVAH,QXO --period 2y
pytest --cov=core --cov=backtest --cov-report=term-missing
```

Docker:

```bash
docker compose up -d bot dashboard    # includes IB Gateway sidecar
```

Stop with `Ctrl+C` or `SIGTERM`; state is saved and IBKR disconnects cleanly.
Open positions keep their broker-side stops and are **not** liquidated.

---

## Configuration highlights

| Section | Key settings |
|---------|--------------|
| `capital` | `total` |
| `ibkr` | `host`, `port`, `account_mode` (paper/live guard) |
| `risk` | `max_risk_percent`, `daily_loss_limit`, `max_drawdown_limit`, `max_absolute_loss` |
| `portfolio` | `max_gross_exposure_pct`, `max_open_positions`, `max_sector_pct`, `max_total_open_risk_pct` |
| `execution` | `use_bracket_orders`, `slippage_ticks`, `order_timeout_seconds` |
| `data` | `min_bars`, `max_age_trading_days`, `max_daily_move_pct` |
| `trading` | `auto_trade`, `market_hours_only`, `scan_interval_seconds` |
| `strategies` | Enabled strategy plugins |
| `notifier` | Telegram/email alerting |

Config is read at startup — restart to apply changes.

---

## Adding a strategy

```python
# core/strategies/my_strategy.py
from core.strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    name = "my_strategy"

    def prefilter(self, df, context):
        return context.quant.get("z_score", 0) >= context.zscore_min, "OK"

    def generate_signal(self, df, context):
        return {"action": "HOLD", "reason": "not implemented"}
```

Register it in `core/strategies/__init__.py`, then enable in `config.yaml`:

```yaml
strategies:
  - name: my_strategy
    enabled: true
```

`main.py` needs no changes.

---

## Audit trail

`logs/trade_blotter.csv` is append-only, one row per decision:

| Event | Meaning |
|-------|---------|
| `SIGNAL` | Strategy output with Z-Score, RSI, volume ratio, levels |
| `REJECT_*` | Rejection with stage (fundamental, data quality, pre-trade, emotion) |
| `ORDER` | Submission with order id, entry, stop, target |
| `FILL` | Execution with fill price, quantity, realised P&L |
| `HALT` / `STARTUP` / `SHUTDOWN` | Lifecycle events |

Rows carry both UTC and local timestamps and are never rewritten.

---

## Documentation

| Document | Contents |
|----------|----------|
| [`RUNBOOK.md`](RUNBOOK.md) | Operations: startup, shutdown, incidents, go-live checklist |
| [`.env.example`](.env.example) | Required environment variables |
| [`archive/README.md`](archive/README.md) | Modules excluded from the live loop |

---

## Notes and limitations

- Folder is still `V3_Bot`; the runtime version is V4.5.
- Daily bars only; the scan cadence suits a daily-bar strategy.
- US market holidays are not modelled — only weekends are excluded.
- Realised P&L relies on IBKR `commissionReport.realizedPNL`.
- `archive/stock_scanner.py` is for offline watchlist building, not the live loop.
- Signal logic and `QuantEngine` behaviour are unchanged from V4.5.
