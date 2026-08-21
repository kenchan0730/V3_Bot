# V4.5 Operations Runbook

Operator manual for the V4.5 trading system. Read the whole document before
enabling `auto_trade`.

---

## 1. Operating modes

| Mode | How to run | Behaviour |
|------|-----------|-----------|
| **Signal-only** (default) | `python main.py` with `auto_trade: false` | Computes signals, writes blotter, sends alerts. No orders. |
| **Dry-run** | `python main.py --dry-run` | Forces signal-only regardless of config. |
| **Single cycle** | `python main.py --once` | One scan then exit. Ignores market-hours gate. Use for smoke tests. |
| **Auto-trade** | `auto_trade: true` in `config.yaml` | Submits bracket orders. Requires the go-live checklist below. |

Auto-trade downgrades itself to signal-only if IBKR cannot be reached at startup.

---

## 2. First-time setup

```bash
cd V3_Bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env        # then edit .env
python test_setup.py        # verify dependencies
pytest -q                   # verify logic
python main.py --once --dry-run   # end-to-end smoke test
```

### Required `.env` values

| Variable | Purpose |
|----------|---------|
| `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID` | Broker connection |
| `IBKR_ACCOUNT_MODE` | `paper` or `live`. Guards against wrong-port connections. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Operator alerts |
| `TOTAL_CAPITAL` | Starting capital |
| `FINNHUB_KEY` | Optional, news sentiment gate |

Never commit `.env`. It is gitignored.

### Port reference

| Port | Meaning |
|------|---------|
| 7497 | TWS paper |
| 7496 | TWS live |
| 4002 | IB Gateway paper |
| 4001 | IB Gateway live |

The connector refuses to connect if `IBKR_ACCOUNT_MODE=paper` but the port is a
live port.

---

## 3. Startup

```bash
# Foreground
python main.py

# Background (Linux/macOS)
nohup python main.py >> logs/stdout.log 2>&1 &

# Docker
docker compose up -d bot dashboard
```

Confirm a healthy start:

1. Log shows `🚀 V4.5 交易機器人啟動` with the expected mode.
2. Log shows `✅ IBKR 已連線` (or a deliberate signal-only warning).
3. Market breadth and exposure lines appear.
4. `logs/state.json` timestamp updates each cycle.
5. Startup alert arrives on Telegram (if enabled).

---

## 4. Shutdown

Send `Ctrl+C` (SIGINT) or `SIGTERM`. The bot then:

1. Stops accepting new symbols.
2. Polls order status one final time.
3. Writes `logs/state.json` including the portfolio snapshot.
4. Disconnects from IBKR.
5. Sends a shutdown alert.

```bash
kill -TERM <pid>          # graceful
docker compose stop bot   # graceful in Docker
```

**Never `kill -9`.** Broker-side stops survive it, but state and the blotter may
lose the final cycle.

Open positions are **not** flattened on shutdown; their bracket stops remain
live at IBKR. To exit flat, close positions manually in TWS first.

---

## 5. Configuration changes

`config.yaml` is read once at startup, so **any change requires a restart**.

| Change | Risk | Notes |
|--------|------|-------|
| `watchlist` | Low | Restart to apply. |
| `risk.*` | High | Re-check sizing with `--once --dry-run` first. |
| `portfolio.*` | High | Tightening while positions are open blocks new entries until exposure falls. |
| `trading.auto_trade` | Critical | Follow the go-live checklist. |
| `execution.slippage_ticks` | Medium | Raises entry limit price. |

Validate before restarting:

```bash
python -c "from core.config_loader import load_config; print(load_config('config.yaml')['risk'])"
```

---

## 6. Go-live checklist (before `auto_trade: true`)

- [ ] `pytest -q` passes.
- [ ] `IBKR_ACCOUNT_MODE=paper` and a paper port are configured.
- [ ] `python main.py --once` connects and logs `✅ IBKR 已連線`.
- [ ] Telegram alerts confirmed working (`notifier.enabled: true`).
- [ ] `logs/trade_blotter.csv` records SIGNAL and REJECT rows.
- [ ] `portfolio.max_open_positions` and `max_gross_exposure_pct` reviewed.
- [ ] `risk.daily_loss_limit` and `max_drawdown_limit` reviewed.
- [ ] Ran unattended on **paper** for one full trading week.
- [ ] Blotter reviewed: every ORDER row has a matching stop price.
- [ ] Verified in TWS that stop orders exist for every open position.
- [ ] Only then switch to live credentials, starting with reduced capital.

---

## 7. Monitoring

### Files to watch

| File | Contents |
|------|----------|
| `logs/trading.log` | Application log, rotated at 10 MB × 5 |
| `logs/state.json` | Capital, P&L, counters, positions, open orders |
| `logs/trade_blotter.csv` | Immutable audit trail |

### Quick checks

```bash
tail -f logs/trading.log
python -c "import json;d=json.load(open('logs/state.json'));print(d['saved_at'],d['total_capital'],d['daily_realized_pnl'],d['halted'])"
grep -c REJECT logs/trade_blotter.csv
streamlit run app.py        # visual dashboard
```

### Alerts you will receive

| Alert | Meaning | Action |
|-------|---------|--------|
| IBKR 連線中斷 | Disconnect during market hours | Check TWS/Gateway; bot auto-retries |
| 數據過期 | Stale bars for a symbol | Check data source; symbol is skipped |
| 數據獲取重複失敗 | 3+ consecutive fetch failures | Check network / rate limits |
| 每日虧損上限觸發 | Daily loss limit hit | **Bot halts.** Review before restart |
| 風險限額觸發 | Drawdown or breadth breach | **Bot halts.** Investigate |
| 訂單異常 | Rejection, cancellation, timeout | Reconcile in TWS |
| 未處理異常 | Unhandled exception | Read traceback in log |

Alerts are throttled to one per key per `notifier.throttle_seconds` (default
300s). Loss-limit and risk-limit alerts bypass throttling.

---

## 8. Incident response

### 8.1 Bot halted on daily loss limit

The halt persists in `logs/state.json` (`halted: true`) and survives restart
until the next trading day.

1. Read `halt_reason`.
2. Review the blotter for the losing trades.
3. Verify positions and stops in TWS.
4. Decide: wait for the daily rollover, or clear the halt deliberately:

```bash
python -c "
import json
p='logs/state.json'
d=json.load(open(p))
d['halted']=False; d['halt_reason']=''
json.dump(d,open(p,'w'),indent=2)
print('halt cleared')
"
```

Only clear a halt after understanding the loss. The limit exists to stop a bad day.

### 8.2 IBKR disconnected

1. Confirm TWS/Gateway is running and logged in.
2. Check for the IBKR daily restart window and 2FA prompts.
3. Confirm `IBKR_CLIENT_ID` is not used by another session.
4. The bot retries with exponential backoff (max 30s, 10 attempts).
5. Open positions keep their broker-side stops while disconnected.

### 8.3 Unprotected position suspected

The bot refuses entries whose bracket fails, but always verify manually:

1. In TWS, compare Positions against open Orders.
2. Any position without a stop: place one manually immediately.
3. Cross-check against ORDER rows in the blotter.

### 8.4 Stale or bad data

Symptoms: `數據過期` or `單日波動 ... 疑似錯誤數據`.

1. The symbol is skipped automatically — no trade is placed.
2. Verify the price independently.
3. For a real halt/delisting, remove the symbol from `watchlist`.
4. Relax `data.max_age_trading_days` only for known holiday gaps.

### 8.5 Corrupt state file

The loader falls back to config defaults and logs a warning.

```bash
mv logs/state.json logs/state.json.bad
python main.py --once --dry-run
```

Then reconcile capital against the broker; the blotter is the authoritative
history.

### 8.6 Crash loop

1. Read the traceback at the end of `logs/trading.log`.
2. Reproduce safely: `python main.py --once --dry-run`.
3. Run `pytest -q` to detect a logic regression.
4. Roll back to the last known-good commit if needed.

---

## 9. Routine maintenance

| Cadence | Task |
|---------|------|
| Daily (pre-open) | Check bot alive, `halted: false`, review overnight alerts |
| Daily (post-close) | Review blotter fills, reconcile P&L against IBKR statement |
| Weekly | Run `python -m backtest --symbols <watchlist>`; review correlation pairs |
| Weekly | Confirm log rotation is working; archive old blotter rows |
| Monthly | Review risk limits vs realised drawdown; `pip list --outdated` |
| Quarterly | Re-run the go-live checklist on paper |

---

## 10. Troubleshooting reference

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `ib_insync 未安裝，IBKR 功能停用` | Missing dependency | `pip install -r requirements.txt` |
| `account_mode=paper 但連接埠是實盤，拒絕連線` | Port/mode mismatch | Align `IBKR_PORT` with `IBKR_ACCOUNT_MODE` |
| `環境變數 X 未設定` | Missing `.env` entry | Add it or use `${X:-default}` |
| No Telegram alerts | Notifier disabled or bad token | Set `notifier.enabled: true`, verify token/chat id |
| Every symbol rejected on fundamentals | Filter too strict for small caps | Relax `fundamental.*` or set `enabled: false` |
| `Z-Score < 下限` for all symbols | Weak breadth raised the floor to 0.8 | Expected defensive behaviour |
| Bot idle | Outside market hours | Expected; or set `market_hours_only: false` |
| Dashboard shows "尚未找到狀態檔" | Bot never ran | Run the bot once |
| Slow scans | Fundamental lookups | Increase `fundamental.cache_ttl_seconds` |

---

## 11. Escalation

Stop trading immediately and investigate if any of these occur:

- A position exists with no stop order at the broker.
- Blotter fills disagree with the IBKR statement.
- Repeated order rejections.
- Daily loss limit hit more than once in a week.
- Any unexplained capital change.

Emergency stop:

```bash
kill -TERM <pid>          # or: docker compose stop bot
```

Then flatten positions manually in TWS if required. The bot does not liquidate
on shutdown.
