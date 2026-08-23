# Personal data folder

All account-specific and runtime files live here. **Do not commit** `.env` or
trading records to git (this folder's `.gitignore` blocks them).

## Setup (first time)

```cmd
cd C:\V4.5_Bot
copy data\.env.example data\.env
notepad data\.env
```

Set at minimum:

| Variable | Example |
|----------|---------|
| `TOTAL_CAPITAL` | `1275` |
| `IBKR_HOST` / `IBKR_PORT` | TWS/Gateway address |
| `IBKR_ACCOUNT_MODE` | `paper` or `live` |

Optional: Telegram, email, Finnhub keys (see `.env.example`).

## Files created at runtime

| File | Purpose |
|------|---------|
| `state.json` | Capital, P&L, halt flag, positions snapshot |
| `trade_blotter.csv` | Append-only audit trail (signals, orders, rejects) |
| `execution_journal.csv` | ProfessionalMind deliberation log |
| `trading.log` | Application log (rotated) |
| `watchlist.json` | Persisted dynamic watchlist |

## Migrating from old `logs/` layout

If you still have files under `logs/`, move them here:

```cmd
move logs\* data\
```

Then run the bot as usual: `python main.py` (loads `data/.env` by default).
