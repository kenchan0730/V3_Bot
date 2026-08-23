# V4.5 Bot documentation

| Document | Description |
|----------|-------------|
| [AUDIT_REPORT.md](AUDIT_REPORT.md) | Full AI audit (architecture, risk, execution, strategy) — uploaded baseline |
| [../data/README.md](../data/README.md) | Personal data folder (`.env`, state, blotter) |
| [../RUNBOOK.md](../RUNBOOK.md) | Operations and go-live checklist |
| [../README.md](../README.md) | Project overview |

## Post-audit fixes (branch `cursor/v45-institutional-upgrade-16b9`)

The following critical items from the audit were implemented after the report was written:

- **Confidence crash** — `parse_confidence()` handles `"HIGH"` string from `TradingSignals`
- **Bracket leg tracking** — OrderManager monitors entry + SL + TP
- **VWAP pullback** — fixed double `/100` in intraday engine
- **Risk tuning** — capital default $1,275; position caps 20%; regime exposure tightens gross limit
- **Data window** — 6-month history for volatility factor
- **Personal data** — all runtime files under `data/`

See git history from commit `9c6390b` onward for details.
