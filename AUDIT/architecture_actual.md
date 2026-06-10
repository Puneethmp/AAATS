# AAATS — Actual Live Architecture (Forensic Map)

> Phase 0 deliverable. Describes what **actually executes**, verified against source,
> not what the blueprint / READMEs claim. Date: 2026-06-10. Read-only audit.

## 1. What actually runs

Entry point (verified `deployment/docker-compose.yml:104`):

```
sh -c "python scripts/init_db.py && python trading/paper_loop.py --market crypto"
```

`paper_loop.py --market crypto` drives `trading/live_paper_runner.py::run_crypto()`
once per cycle. `CYCLE_INTERVAL_SEC = 900` (15 min, `live_paper_runner.py:2288`).

| Container | Role | Status |
|---|---|---|
| `aaats-paper-crypto` | **the only active trading loop** — `MARKET=crypto`, `TRADING_MODE=paper` | ACTIVE |
| `aaats-paper-us` | `MARKET=us` | defined; **not exercised** (loop branches crypto/india only) |
| `aaats-paper-india` | `MARKET=india` | INACTIVE — `INITIAL_CAPITAL["india"]=0.0` (`live_paper_runner.py:122`) |
| `aaats-metrics` | Prometheus exporter `:9091` | ACTIVE (read-only) |
| `aaats-dashboard` | Streamlit `:8501` | ACTIVE (read-only) |
| `aaats-prometheus` / `aaats-grafana` | metrics/observability | ACTIVE |
| `aaats-watchdog` / `aaats-telegram-bot` | liveness + alerts | ACTIVE |

Starting capital (crypto): **$110** (`live_paper_runner.py:123`).

## 2. Strategies that emit trades (live book)

Only **three** strategies have produced trades since the 2026-05-23 ledger reset:

| ID | File | Universe | Cost model in PnL | Verdict on record |
|---|---|---|---|---|
| C1 stat-arb | `trading/stat_arb.py` | BTC/ETH pair | **none** (raw prices) | no validated edge (CLAUDE.md) |
| C3 altcoin reversion | `trading/altcoin_reversion.py` | wide alt universe (POL, TON, OPN, PENDLE, GPS, ADA, ALGO, AVAX…) | **none** (raw prices) | window-dependent / NO-GO |
| C6 bollinger range | `trading/bollinger_range.py` | alt universe | **none** (raw prices) | "signal density only, not PnL" (own docstring) |

- **C2 momentum** (`trading/momentum_breakout.py`): present, **no trades** in window.
- **C5b funding-arb** (`trading/funding_arb.py`): **disabled at source** (`halted_src`).
- The 6-symbol `CRYPTO_SYMBOLS` majors list feeds the consensus-vote / ML / `execute()`
  path; C3 and C6 maintain their **own** alt universes independent of that list.

### Critical: two divergent fill paths
- `execute()` in `live_paper_runner.py:1212` applies `_fill_price()` slippage
  (`SLIPPAGE={"crypto":0.001}`, vol-scaled) — used by the majors/standalone-routed path.
- **C1/C3/C6 do NOT use it.** They call `execution.paper_trader.record_trade()` directly
  with PnL computed from **raw prices, zero fees, zero slippage, zero funding**:
  - C3 `altcoin_reversion.py:625` `pnl = size*(current_price-entry)/entry`
  - C6 `bollinger_range.py:322` `pnl = size_usd*(price-entry_price)/entry_price`
  - C1 `stat_arb.py:267-268` `pnl_a=(price_a-entry_a)*shares_a`
- A separate rigorous `execution/fill_model.py` (real spot/perp fees, slippage, funding)
  **exists but is not wired into the live PnL path.** It is dead relative to production.

## 3. Models / gates

- **HMM regime** (`intelligence/regime/`): refit ~every 4h in-memory; **weights votes only,
  does not hard-block**. Falls back to a rule-based regime when stale.
- **XGBoost ML gate** (`data/ml/model_crypto.json`, trained 2026-05-07, val_acc **0.5508**):
  maps confidence→size multiplier via `strategies/configs/_ml_gate.yaml`; only
  `confidence<0.40` → scale 0 (skip). Gates the majors/`execute()` path; **C3/C6 do not
  consult it.** (Prior "blocks ALL signals" defect: NOT reproduced — gate currently passes
  most signals. Verify threshold/feature-drift in Phase 2.)

## 4. Schedulers / collectors

- **Auto-push** `scripts/box/aaats-autopush-v3.sh`, `*/15 * * * *`: `git reset --hard
  origin/main` + snapshot `runtime/` state + `git push`. Commits trade DB, positions,
  portfolio, last 500 log lines to a GitHub repo. **No secrets hardcoded; `.env` is
  gitignored.** Residual risk: log lines could leak an error containing a key. (Mandate
  flags this; address in Phase 1.)
- **OI collector** `scripts/box/aaats-t3-oi-collector.py`, hourly → box-local
  `/home/aaats/t3/t3_positioning.db`. Pure forward data capture (T3 positioning thesis,
  usable ~2027). **DO NOT DELETE** (collector or its data) per mandate.
- Daily digest GitHub Action 06:00 UTC; box heartbeat checker `*/5`.

## 5. Live-order safety

No `create_order` / private-trade endpoint is called anywhere in `execution/`. Binance/Angel
credentials are used for **public data only** (OHLCV, orderbook). `TRADING_MODE=paper` is set
but **not enforced in code** — a config flip + a new order call would reach live keys.
Recommend a hard runtime guard in Phase 3. **No live path exists today.**
