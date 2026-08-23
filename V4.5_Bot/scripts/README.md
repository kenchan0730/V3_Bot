# Utility scripts (not part of the live trading loop)

| Script | Purpose |
|--------|---------|
| `diagnose_env.py` | Quick Python/package import check for local setup. |
| `check_breadth.py` | Standalone market-breadth score printer for manual verification. |
| `refresh_watchlist.py` | Rebuild core + satellite watchlist from scanner + quant rank. |
| `factor_sensitivity.py` | Grid-search QuantEngine factor weights against backtest profit factor. |

Run from the `V4.5_Bot/` directory:

```bash
python scripts/diagnose_env.py
python scripts/check_breadth.py
python scripts/factor_sensitivity.py --symbols AVAH,QXO --period 2y
```

## Validating factor weights

The default 35/25/20/20 split is an engineering prior, not a fitted result.
`factor_sensitivity.py` sweeps the weight simplex and reports how much profit
factor actually moves:

- **Narrow spread** — the strategy is insensitive to weights; the default is
  fine and the "four-factor model" claim is not doing much work.
- **Wide spread** — weights matter, so the shipped default needs evidence (or
  replacement) before being trusted in production.

Note the volatility factor only activates with >= 120 bars of history, so run
the sweep on at least a 1-year period.
