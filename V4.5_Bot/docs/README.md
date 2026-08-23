# V4.5 Bot documentation

| Document | Description |
|----------|-------------|
| [AUDIT_REPORT.md](AUDIT_REPORT.md) | First AI audit (baseline 6.5/10) |
| [AUDIT_REPORT_V2.md](AUDIT_REPORT_V2.md) | Second, line-by-line audit (baseline 6.5/10) |
| [AUDIT_RESPONSE.md](AUDIT_RESPONSE.md) | **Item-by-item response**: what was fixed, where, and what is still open |
| [../data/README.md](../data/README.md) | Personal data folder (`.env`, state, blotter) |
| [../RUNBOOK.md](../RUNBOOK.md) | Operations and go-live checklist |
| [../README.md](../README.md) | Project overview |

## What changed since the audits

The audits scored the system 6.5/10, held back by one bug that blocked all
order submission plus structural risk-control gaps. Both critical paths and
every 🟡/🟢 recommendation except the `EntryPipeline` refactor have been
addressed. See [AUDIT_RESPONSE.md](AUDIT_RESPONSE.md) for the full mapping.

Headline fixes:

1. **Orders can actually be submitted** — numeric `confidence` removed the
   `ValueError` that killed every buy signal at the last step.
2. **Naked positions are detected and repaired** — all three bracket legs are
   tracked, and a dead stop triggers an alert plus an automatic re-arm.
3. **Risk limits are coherent** — one source of truth for concentration, regime
   exposure as a hard book cap, and a budget check so a wider stop cannot
   increase dollar risk.
4. **Backtests no longer flatter themselves** — commissions, slippage and the
   live approval chain all apply.
5. **Silent failures became loud** — stale VIX, unusable intraday data and an
   inactive volatility factor are now reported rather than assumed fine.

Tests: **459 passing** (347 at audit time).

## Honest limitations

Engineering quality is not edge. The deliberation layer targets mature
automation, not a guaranteed win rate; live results still depend on market
conditions, execution quality and disciplined operation. `auto_trade` should
stay `false` until the checklist at the end of
[AUDIT_RESPONSE.md](AUDIT_RESPONSE.md) passes on a paper account.
