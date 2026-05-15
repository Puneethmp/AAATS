# AAATS 2-Day Sprint — Build Manifest & Deploy Guide

**Date:** 2026-05-11
**Sprint goal:** Close 4 of 6 load-bearing gaps before live trading.

This document lists every file changed/created in this sprint, what each
does, and the exact commands to deploy to Contabo.

---

## What was built (6 files)

### 1. `execution/idempotency.py` — NEW
Deterministic `client_order_id` derivation + SQLite dedupe layer.
Closes **Gap 4** (idempotent order identity).

Key functions:
- `make_client_order_id(strategy, market, symbol, side, bar_ts, nonce=0)` →
  same inputs → same 32-char hex id forever. Bar timestamp normalised to
  nearest UTC minute so microsecond drift doesn't break determinism.
- `make_correlation_id()` → fresh uuid4 to thread intent → decision → fill.
- `dedupe_check(db, cli_id)` → returns `(existed, prior_trade_id)` before insert.
- `_ensure_dedupe_index(db)` → idempotent column + UNIQUE INDEX migration.

### 2. `execution/paper_trader.py` — PATCHED
`record_trade()` now:
- Accepts optional `client_order_id`, `correlation_id`, `bar_ts`, `nonce`.
- Derives them automatically if not supplied.
- Calls `dedupe_check()` before INSERT; if duplicate, returns prior `trade_id`
  with `WARN` log and writes NOTHING.
- Catches `sqlite3.IntegrityError` from UNIQUE INDEX (race condition belt-
  and-braces) and returns the winner's id.
- Logs cli + corr ids on every trade line.

### 3. `scripts/health_http_server.py` — NEW
FastAPI server on port `8002` wrapping the existing
`scripts/health_check.run_health_check()`.
Closes container `UNHEALTHY` status by giving Docker an HTTP target.

Endpoints:
- `GET /health` → 200 if OK or WARNING, **503 if CRITICAL** (Docker marks
  unhealthy)
- `GET /health/live` → 200 always (liveness probe)
- `GET /` → endpoint inventory

### 4. `foundation/decision_ledger.py` — NEW
Thin ergonomic helper over `foundation/audit_trail.AuditTrail`.
Closes **Gap 5** (structured event log adoption).

Provides correlation-threaded methods:
- `start(symbol, strategy, market)` → fresh `correlation_id`
- `signal(corr_id, ...)` → strategy signal
- `risk(corr_id, ...)` → risk engine decision
- `intent(corr_id, ...)` → order intent
- `fill(corr_id, ...)` → fill confirmation
- `skip(corr_id, ...)` → deliberate skip (gate, cap, filter)
- `error(corr_id, ...)` → unexpected error
- `trace(corr_id)` → full lifecycle for postmortem

Use in `live_paper_runner.execute()` and per-strategy files
(C1/C2/C3/C5b) when convenient — non-breaking, drop-in.

### 5. `scripts/reconcile_intracycle.py` — NEW
Intra-cycle reconciliation worker.
Closes **Gap 3** (silent state divergence).

Compares two truth sources:
- **A:** `data/paper_positions.json` (in-memory state written by main loop)
- **B:** Net positions computed from `data/paper_trades.db` (BUYS − SELLS,
  excluding `C5b_funding_arb` which is delta-neutral by design)

Drift policy:
- `> 0.5%` → WARN (audit + log)
- `> 2.0%` → **HALT** (fires `foundation.kill_switch.halt()` for the affected
  market)
- Symbol present in only one source → **HALT** (catastrophic state corruption)

Modes:
- Library: `from scripts.reconcile_intracycle import reconcile_now`
- CLI: `python scripts/reconcile_intracycle.py [--market crypto] [--json] [--no-halt]`
- Cron: every 60 s in a watchdog process (sample systemd unit below)

### 6. `monitoring/telegram_bot.py` — PATCHED
Added `/killall` command with TOTP-based 2FA.

Flow:
1. User: `/killall`
2. Bot: asks for 6-digit code from authenticator app
3. User: `123456`
4. Bot: validates against `KILLALL_TOTP_SECRET` (±1 step = 60 s window)
5. If valid: writes `data/halt_state.json` (halts ALL markets) + legacy
   `data/kill_switch.json` + audit-trail entry
6. If invalid: rejects, clears state, logs warning

To configure:
```bash
python -c "import pyotp; print(pyotp.random_base32())"
# Add seed to .env as KILLALL_TOTP_SECRET=...
# Scan QR or type seed into Google Authenticator / Authy
```

Differences from existing `/stop`:
- 2FA (cryptographic) vs typed "CONFIRM STOP" (anyone with bot access)
- Halts ALL markets atomically
- Writes `halt_state.json` (the file foundation/kill_switch.py reads)
- Single message exchange — faster in emergency

---

## Deploy commands

Assumes:
- Local AAATS dir: `C:\Users\udaym\OneDrive\Desktop\Puneeth`
- Contabo SSH: `aaats@100.95.126.39` (Tailscale)
- Contabo AAATS dir: `/home/aaats/aaats/`
- Bot runs in a separate container `aaats-telegram-bot`

### Step 1 — Generate TOTP secret (one-time)

```powershell
# On your Windows machine
cd C:\Users\udaym\OneDrive\Desktop\Puneeth
venv\Scripts\python.exe -c "import pyotp; print(pyotp.random_base32())"
```

Copy the output. Add to BOTH your Authenticator app AND `.env`:

```bash
# .env (on local + Contabo)
KILLALL_TOTP_SECRET=THE_BASE32_SEED_FROM_ABOVE
```

### Step 2 — Copy changed files to Contabo

```bash
# From local PowerShell or WSL — use your existing deploy script
# (deploy_to_contabo.py per memory) and ADD these new modules to its INCLUDE list:
#
#   execution/idempotency.py
#   execution/paper_trader.py             (modified)
#   foundation/decision_ledger.py
#   scripts/health_http_server.py
#   scripts/reconcile_intracycle.py
#   monitoring/telegram_bot.py            (modified)
#
# Then:
python deploy_to_contabo.py
```

If deploy_to_contabo.py path is wrong, the raw scp equivalent:

```bash
scp -i ~/.ssh/aaats_contabo \
    execution/idempotency.py execution/paper_trader.py \
    foundation/decision_ledger.py \
    scripts/health_http_server.py scripts/reconcile_intracycle.py \
    monitoring/telegram_bot.py \
    aaats@100.95.126.39:/home/aaats/aaats/
```

(Adjust per-file paths to match the directory structure on Contabo.)

### Step 3 — Apply schema migration inside `aaats-paper-crypto` container

```bash
# SSH in
ssh aaats@100.95.126.39

# Force the schema migration by importing the idempotency module —
# the _ensure_dedupe_index() call adds the columns + UNIQUE INDEX.
docker exec aaats-paper-crypto python -c \
  "from execution.idempotency import _ensure_dedupe_index; \
   _ensure_dedupe_index('/app/data/paper_trades.db'); \
   print('schema migrated OK')"

# Verify columns exist:
docker exec aaats-paper-crypto python -c \
  "import sqlite3; c = sqlite3.connect('/app/data/paper_trades.db'); \
   print([r[1] for r in c.execute('PRAGMA table_info(paper_trades)').fetchall()])"
# Should include 'client_order_id' and 'correlation_id'
```

### Step 4 — Restart paper-crypto container

```bash
docker restart aaats-paper-crypto
docker logs --tail=80 aaats-paper-crypto
# Look for: PAPER ... | cli=XXXXXXXXXXXX | corr=XXXXXXXX
```

### Step 5 — Add `/health` endpoint to docker-compose

Edit `deployment/docker-compose.yml` (or wherever the compose file lives
on Contabo). For service `aaats-paper-crypto` add:

```yaml
  aaats-paper-crypto:
    # ... existing config ...
    command: >
      bash -c "
        python scripts/health_http_server.py &
        python trading/live_paper_runner.py --market crypto
      "
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
```

Notes:
- The `&` background-starts the health server alongside the trader.
- If your compose already has a `command:`, merge carefully.
- `curl` must be installed in the container image. If not, swap to
  `["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8002/health').read()"]`.

Then redeploy:

```bash
cd /home/aaats/aaats/deployment
docker compose up -d --no-deps aaats-paper-crypto
docker ps   # verify status changes from "(unhealthy)" → "(healthy)" within ~2 min
```

### Step 6 — Schedule the reconciliation worker

Two options:

**A. Inline at end of each cycle (cleanest):**

Add to `trading/live_paper_runner.py` `main()` loop at end of cycle
(line ~1536, before `log.info("Cycle X done...")`):

```python
# Intra-cycle reconciliation (gap 3)
try:
    from scripts.reconcile_intracycle import reconcile_now
    rec = reconcile_now(markets=["crypto"])
    if rec.halted:
        log.critical("Reconciliation HALTED trading — investigate before resume")
        break  # exit main loop
except Exception as exc:
    log.error("Reconciliation worker error: %s", exc, exc_info=True)
```

**B. Standalone systemd timer (more independent):**

Create `/etc/systemd/system/aaats-reconcile.service` on Contabo:

```ini
[Unit]
Description=AAATS Intracycle Reconciliation Worker
After=docker.service

[Service]
Type=oneshot
User=aaats
WorkingDirectory=/home/aaats/aaats
ExecStart=/usr/bin/docker exec aaats-paper-crypto python /app/scripts/reconcile_intracycle.py --market crypto --json
```

And `/etc/systemd/system/aaats-reconcile.timer`:

```ini
[Unit]
Description=Run AAATS reconciliation every 60s

[Timer]
OnBootSec=2min
OnUnitActiveSec=60s
Persistent=true

[Install]
WantedBy=timers.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aaats-reconcile.timer
sudo systemctl list-timers | grep aaats
```

**Recommendation:** start with Option A (inline) — simpler, no additional
service to maintain, fires exactly when the runner finishes its cycle.

### Step 7 — Restart telegram-bot with the new /killall

```bash
ssh aaats@100.95.126.39
# Make sure KILLALL_TOTP_SECRET is in the bot container's .env
docker restart aaats-telegram-bot
docker logs --tail=40 aaats-telegram-bot
# Look for: "Bot running. Polling for commands..."

# Test /killall flow:
#   1. Send /help → confirm /killall is listed
#   2. Send /killall → bot asks for code
#   3. Send wrong code → bot rejects, no halt
#   4. Send fresh code → bot confirms halt, writes halt_state.json
#   5. Verify: docker exec aaats-telegram-bot cat /app/data/halt_state.json
#      → {"us": true, "india": true, "crypto": true}
#   6. Resume:
#      docker exec aaats-paper-crypto python scripts/emergency_resume.py \
#        --market all --authorized-by Puneeth --reason "test_complete"
```

---

## Verification checklist

After deploy, work through this list before considering Day 1+2 done:

### Gap 4 — Idempotency
- [ ] `paper_trades.db` has `client_order_id` and `correlation_id` columns
- [ ] UNIQUE INDEX `ux_paper_trades_client_order_id` exists
- [ ] Manual test: invoke `record_trade(...)` twice with same params, second
      returns the first call's trade id (no duplicate row)
- [ ] Log lines now include `| cli=XXX | corr=XXX`

### Gap 5 — Decision Ledger / Event Log
- [ ] `data/audit_trail.db` exists and is being written
- [ ] At least one row with `module='decision_ledger'` after a full cycle
      (will appear once `live_paper_runner.py` is instrumented — pending
      Day 1 step 4 wiring)
- [ ] `audit_trail.query(market='crypto', event_type='SIGNAL')` returns
      rows with correlation_id field in details

### Gap 3 — Reconciliation
- [ ] `python scripts/reconcile_intracycle.py --market crypto` runs clean
      on first invocation (passed=True)
- [ ] Either inline call OR systemd timer scheduled
- [ ] Manually corrupt `paper_positions.json` (e.g. inflate a share count
      by 10%) → next run halts → `data/halt_state.json` shows
      `{"crypto": true}` → resume tested

### Gap 6 — Telegram /killall
- [ ] `KILLALL_TOTP_SECRET` in `.env` AND in authenticator app
- [ ] `/help` lists `/killall`
- [ ] Wrong TOTP code → bot rejects
- [ ] Correct TOTP code → `halt_state.json` written + main loop halts
      within one cycle
- [ ] Audit trail has `module='telegram_killall'` entry

### Container health
- [ ] `docker ps` shows `aaats-paper-crypto (healthy)` (not unhealthy)
- [ ] `curl http://100.95.126.39:8002/health` from Tailscale returns 200 +
      JSON with `"overall_status": "OK"`

---

## Gap 1 + Gap 2 — Also built (extended sprint)

### 7. `execution/fill_model.py` — NEW (Gap 1)
Realistic fill simulator. Used by PaperExecutor.

- `FillModel.simulate_taker()` — walks live L20 depth, applies latency-driven
  adverse move scaled by 24-bar volatility, plus microstructure noise.
- `FillModel.simulate_maker()` — **honest maker fills**: requires both
  (a) limit price strictly inside book AND (b) an actual trade printed
  through your price during wait window. No bid-ask-oscillation false fills.
- Fee defaults: Binance VIP-0 (spot 10/10 bps, USDT-M 2/5 bps). Override per
  trader tier via constructor.

### 8. `execution/paper_executor.py` — NEW (Gap 1)
Singleton bridge between strategies and FillModel.

- `PaperExecutor.singleton().simulate_and_record(...)` — one call replaces
  the existing `_fill_price()` + `record_trade()` pair in `live_paper_runner`.
- Fetches `ccxt.fetch_order_book(limit=20)` and `fetch_trades(limit=50)`
  per BUY/SELL.
- ~6 fetches per 15-min cycle = trivially within Binance public rate limits.
- Falls back to old slippage if book fetch fails (never blocks trading).
- Auto-writes to paper_trades.db AND decision_ledger with correlation_id.

### 9. `execution/oms.py` — NEW (Gap 2)
Order Management System with explicit state machine.

State machine: `NEW → SUBMITTED → ACK → WORKING → (PARTIAL_FILL)* → FILLED`
Plus terminal alternates from any state: `CANCELLED | REJECTED | EXPIRED`.

Two SQLite tables in a separate `data/oms.db`:
- `oms_orders` — one row per order with current state, qty_filled,
  avg_fill_price, fees_total
- `oms_transitions` — append-only history of every state change with
  event_data

Public API:
```python
oms = OMS()
order_id = oms.create_intent(OrderIntent(...))     # → NEW
oms.submit(order_id, venue_order_id=None)          # → SUBMITTED
oms.ack(order_id, venue_order_id="abc")            # → ACK → WORKING
oms.partial_fill(order_id, qty, price, fees)       # → PARTIAL_FILL → FILLED
oms.cancel(order_id, reason="strategy_pulled")     # → CANCELLED
oms.resume_inflight()                               # on restart
```

Invalid transitions raise `ValueError` immediately. Process restart can call
`resume_inflight()` to find unresolved orders.

**Phase 1 note:** OMS is OPTIONAL for paper trading. AAATS keeps using
`record_trade()` directly via PaperExecutor in paper mode. Switch ON for live
trading by routing every order intent through `OMS.create_intent()` first.

---

## Integration patches (already in code)

### `trading/live_paper_runner.py` — PATCHED
Added inline reconciliation call at end of every cycle (after the
`time.sleep(sleep_sec)` setup, before the actual sleep). If reconciliation
halts, the main loop exits and requires `emergency_resume.py` to restart.

```python
try:
    from scripts.reconcile_intracycle import reconcile_now
    _rec = reconcile_now(markets=_markets_to_check)
    if _rec.halted:
        log.critical("🛑 RECONCILIATION HALTED trading")
        break
except Exception as _rec_exc:
    log.error("Reconciliation worker error (non-fatal, continuing): %s", _rec_exc)
```

---

## Extended deploy steps (Gap 1 + Gap 2)

### Step 8 — Wire PaperExecutor (optional, recommended for proof criterion #8)

In `trading/live_paper_runner.py`, swap the existing `execute()` body's BUY/SELL
path from inline `_fill_price()` to PaperExecutor. Minimal change:

```python
# Find this in execute() BUY branch:
fill    = _fill_price(last_price, "BUY", market, features)
value   = shares * fill
# ...record_trade(...)

# Replace with (crypto only):
if market == "crypto":
    from execution.paper_executor import PaperExecutor
    _result = PaperExecutor.singleton().simulate_and_record(
        market=market, symbol=symbol, side="BUY",
        intended_price=last_price, size=shares,
        strategy=strategy or f"{market}_directional",
        signal=signal, regime=regime,
        confidence=confidence, ml_scale=ml_size_scale,
        features=features, fill_type="TAKER",
    )
    if _result is None or not _result.filled:
        return
    fill = _result.fill_price
    value = _result.fill_price * _result.filled_size
    shares = _result.filled_size   # use the actual filled qty
else:
    fill = _fill_price(last_price, "BUY", market, features)
    value = shares * fill
    # ...record_trade(...) as before
```

Do the same for SELL branch. India NSE keeps the existing path (PaperExecutor
is crypto-only Phase 1).

**Why optional**: the OLD `_fill_price()` path still works. PaperExecutor
adds fidelity (proof criterion #8) but you can wire it later if you want to
ship the 4 closed-gap changes first and add this in a second deploy.

### Step 9 — OMS standalone test (don't wire yet)

OMS is built and ready but not yet routing live order flow. For Phase 1
paper trading, leave it un-wired. To verify it works:

```bash
docker exec aaats-paper-crypto python -c "
from execution.oms import OMS, OrderIntent
oms = OMS()
oid = oms.create_intent(OrderIntent(
    strategy='test', market='crypto', symbol='BTC/USDT',
    side='BUY', qty=0.001, intent_price=40000.0, order_type='MARKET',
))
print('created:', oid)
oms.submit(oid)
oms.ack(oid, venue_order_id='test_venue_42')
oms.partial_fill(oid, fill_qty=0.001, fill_price=40005.0, fees=0.02)
order = oms.get(oid)
print('final state:', order.state, 'filled:', order.qty_filled)
print('transitions:', len(oms.transitions(oid)))
"
# Expected: state=FILLED, filled=0.001, transitions=5
```

When you go live, OMS becomes the central order-flow router. The broker
adapter will:
1. Call `oms.create_intent()` → get order_id + client_order_id
2. Call `oms.submit()` → POST to Binance with client_order_id header
3. On WS event: call `oms.ack()` / `partial_fill()` / etc.
4. On restart: call `oms.resume_inflight()` and reconcile each open order.

---

## Memory update needed

After verification, save this status:

```
2-day sprint EXTENDED — ALL 6 gaps now have code shipped.

- Gap 1 (paper fidelity): execution/fill_model.py + execution/paper_executor.py
- Gap 2 (OMS state machine): execution/oms.py (built, unwired for paper)
- Gap 3 (reconciliation): scripts/reconcile_intracycle.py + inline call wired
- Gap 4 (idempotency): execution/idempotency.py + paper_trader patch
- Gap 5 (event log): foundation/decision_ledger.py + audit_trail wider use
- Gap 6 (kill switch): telegram_bot /killall with TOTP 2FA

Wiring status:
- Gap 3: WIRED in live_paper_runner.main() end-of-cycle
- Gap 4: WIRED via paper_trader.record_trade() automatic derivation
- Gap 5: AVAILABLE (decision_ledger.py) — wire into execute() incrementally
- Gap 6: WIRED in telegram_bot.py (needs TOTP secret in .env)
- Gap 1: AVAILABLE (paper_executor.py) — replace _fill_price() call in
        live_paper_runner.execute() to activate (step 8 in deploy guide)
- Gap 2: BUILT, UNWIRED for paper — wire on live trading switchover
```

## Complete file manifest (9 files)

| # | File | Status | Gap |
|---|---|---|---|
| 1 | `execution/idempotency.py` | NEW | 4 |
| 2 | `execution/paper_trader.py` | PATCHED | 4 |
| 3 | `foundation/decision_ledger.py` | NEW | 5 |
| 4 | `scripts/health_http_server.py` | NEW | (container health) |
| 5 | `scripts/reconcile_intracycle.py` | NEW | 3 |
| 6 | `monitoring/telegram_bot.py` | PATCHED | 6 |
| 7 | `execution/fill_model.py` | NEW | 1 |
| 8 | `execution/paper_executor.py` | NEW | 1 |
| 9 | `execution/oms.py` | NEW | 2 |
| -- | `trading/live_paper_runner.py` | PATCHED (inline reconcile) | 3 wiring |
