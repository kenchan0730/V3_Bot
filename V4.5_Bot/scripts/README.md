# Utility scripts (not part of the live trading loop)

| Script | Purpose |
|--------|---------|
| `diagnose_env.py` | Quick Python/package import check for local setup. |
| `check_breadth.py` | Standalone market-breadth score printer for manual verification. |
| `refresh_watchlist.py` | Rebuild core + satellite watchlist from scanner + quant rank. |

Run from the `V4.5_Bot/` directory:

```bash
python scripts/diagnose_env.py
python scripts/check_breadth.py
```
