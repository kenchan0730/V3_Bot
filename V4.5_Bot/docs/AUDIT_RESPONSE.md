# Audit response — item-by-item

Tracks every finding in [`AUDIT_REPORT_V2.md`](AUDIT_REPORT_V2.md) (baseline
score **6.5/10**) against the code that addresses it.

Test suite: **459 passing** (was 347 at audit time).

---

## 🔴 Critical

| # | Finding | Status | Where |
|---|---------|--------|-------|
| 1 | `float("HIGH")` crashed every real STRONG_BUY | Fixed | `core/trading_signals.py` returns numeric `confidence`; `core/signal_utils.py:parse_confidence` keeps legacy strings safe; `tests/test_signal_mind_integration.py` runs the real signal through `approve_entry` |
| 2 | OrderManager tracked only the bracket parent, so a rejected stop left a naked position undetected | Fixed | `OrderManager.track_bracket` registers all three legs; `check_protection()` detects a dead stop, alerts, and re-arms via `IBKRConnector.place_protective_stop`; called each cycle from `TradingBot.verify_stop_protection` |
| 3 | VWAP pullback divided by 100 twice (0.8% acted as 0.008%) | Fixed | `core/intraday_engine.py`; regression test asserts `vwap * 1.008` |
| 4 | `.env` default capital $385 vs real $1,275 | Fixed | `config.yaml` default `1275.0`; `data/.env.example` updated |

## 🟡 Enhancements

| # | Finding | Status | Where |
|---|---------|--------|-------|
| 5 | Regime exposure only scaled new orders; book gross cap stayed at 100% | Fixed | `TradingBot._effective_gross_cap()` = `min(config, regime exposure)`, applied in `check_gates()` and `validate_pre_trade()`; `max_gross_exposure_pct` lowered to 60% |
| 6 | 50% single-name cap; two config keys with no single source of truth | Fixed | Both caps at 20%; `RiskManager.set_concentration_cap()` injects `Portfolio.max_symbol_pct` at startup |
| 7 | `execution_score` was journal-only, never affecting size | Fixed | `ProfessionalMind.conviction_factor()` tiers (≥9 full, ≥7 ×0.75, ≥6 ×0.5, else ×0.35, <4 reject); applied in `handle_buy` |
| 8 | Backtest skipped ProfessionalMind, commissions and slippage | Fixed | `BacktestEngine` applies entry/exit slippage + IBKR-style commission, accepts `professional_mind`, reports `total_costs` and `mind_rejections` |
| 9 | Multi-pattern bars: `entry`/`stop` overwritten by the last match, not the strongest | Fixed | `CandlePatterns` records every trigger and takes levels from the dominant aligned pattern (exposed as `driver`) |
| 10 | Intraday data had no freshness/outlier gate | Fixed | `data_utils.intraday_quality_report()` + `IntradayEngine.quality_gate()`, enforced in `evaluate_entry` |

## 🟢 Long-term

| # | Finding | Status | Where |
|---|---------|--------|-------|
| 11 | Factor weights had no statistical validation | Addressed | `scripts/factor_sensitivity.py` grid-searches the weight simplex against profit factor; weights now read from `config.zscore.weights` (previously hard-coded and ignored); docstring states the default is an unvalidated prior |
| 12 | `handle_buy()` too long, no per-stage tests | Partial | Conviction, risk-budget and protection stages extracted into separately tested units; the full `EntryPipeline` refactor is still open |
| 13 | No Docker build/smoke test in CI | Fixed | `.github/workflows/ci.yml` builds the image and constructs `TradingBot` inside it |
| 14 | `compression_scores` Python loop made backtests O(N²) | Fixed | `QuantEngine.compression_series()` vectorised; equivalence test against the original loop |

## Additional issues found and fixed

| Finding | Where |
|---------|-------|
| Volatility factor silently zero on short history, redistributing its 20% weight | 6-month fetch window; `factors_active` / `volatility_factor_active` now reported |
| Widening an ATR stop while shrinking share count could raise dollar risk | `DynamicPositionSizer.enforce_risk_budget()` caps shares to the per-trade budget |
| `max_drawdown_limit` (10%) and `max_absolute_loss` (8%) fired together, so there was effectively one line | Separated to 12% / 8% plus a 6% warning band that de-risks first |
| `yf.download` had no timeout and could stall the cycle | `data.fetch_timeout_seconds` and `intraday.fetch_timeout_seconds` |
| VIX fetch failure silently reused a stale value that all regime logic depends on | Logs, blotter `VIX_STALE` event and operator alert |
| Manual bracket fallback lacked an OCA group | `ocaGroup` + `ocaType=1` on both exit legs |

---

## Remaining open items

These are deliberately not done and are the honest gap to a perfect score:

- **`EntryPipeline` refactor** — `handle_buy()` is shorter and its stages are
  individually tested, but it is still one function.
- **Fitted factor weights** — the tooling to validate them exists; the sweep
  needs real history and a decision, which is a research task, not a code change.
- **Fixed-2% stop mode** — the audit noted this is a philosophy choice. The
  system remains ATR/structure-based; a config switch was not added.
- **Live-edge validation** — no amount of code review substitutes for paper
  trading. Expect a 6–7/10 realised edge regardless of engineering quality.

## Before enabling `auto_trade`

1. Confirm `data/.env` has `TOTAL_CAPITAL=1275`.
2. Run `python main.py --once --dry-run` and confirm a STRONG_BUY reaches
   "Bracket 已送出" without `分析 XX 時發生錯誤`.
3. Paper-trade one bracket and verify all three legs appear in TWS.
4. Kill the stop leg manually in TWS and confirm the bot detects it and
   re-arms within one cycle.
