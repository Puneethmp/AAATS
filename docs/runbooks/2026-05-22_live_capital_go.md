# Live-Capital Go Runbook — $25 first tranche

**Target date:** 2026-05-22 (or any day operator chooses after the three pre-flight verifications in `docs/decisions/2026-05-22_live_readiness.md` pass)
**Authority:** operator (Puneeth) executes; Claude advises but does not flip the switch
**Tranche size:** $25 USD (NOT $100). Escalation via separate runbooks: 2026-05-29 $50, 2026-06-05 $100.

---

## Pre-flight (T-30min)

Three verifications from `docs/decisions/2026-05-22_live_readiness.md`. None require Claude. All require Tailscale SSH to `aaats@100.95.126.39`.

### PF1 — Auto-readiness gate re-evaluation

```bash
ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python -m scripts.evaluate_live_readiness 2>&1'
```

**Pass criteria:**
- `"allowed": true`
- `"readiness_score" >= 90`
- `"blockers": []`

**If `total_trades < 50`** — the auto-gate is using a stale snapshot. Manually verify trade count:

```bash
ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python -c "
import sqlite3
c = sqlite3.connect(\"/app/data/paper_trades.db\")
print(c.execute(\"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM paper_trades\").fetchone())
"'
```

If real count > 50 but gate says NOT READY, find and fix `scripts/evaluate_live_readiness` before proceeding. **Do not override the gate without understanding why it's stuck.**

### PF2 — Last-24h reconcile clean

```bash
ssh aaats@100.95.126.39 'cat /home/aaats/aaats/data/share_equality_mismatches.json'
ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python -m scripts.reconcile_intracycle --no-halt 2>&1 | tail -30'
```

**Pass criteria:**
- `share_equality_mismatches.json` shows only known historical entries (TON/USDT, FET/USDT) OR is `{}`
- Reconcile output shows no NEW symbols added in last 24h
- No `HALT` events in last 24h container logs

### PF3 — Telegram alert chain synthetic test

Per CLAUDE.md recipe — fire `_TEST_LIVE_2026_05_22_` synthetic WARN and confirm Telegram delivery:

> **NOTE: the host file is root-owned; write via `docker exec`, not host `echo >`.**
> `data/` state files are written by `aaats-paper-crypto` running as uid=0, so a
> host-side `ssh ... 'echo ... > /home/aaats/aaats/data/<file>'` fails with
> `Permission denied`. Pipe the payload into the owning container instead
> (`/app/data` is the same bind mount; the container is root so the write lands).
> See CLAUDE.md gotcha #12 and docs/known_issues/2026-05-22_share_equality_alert_chain.md (2026-05-31).

```bash
ssh aaats@100.95.126.39 'echo "{\"_TEST_LIVE_2026_05_22_|_TEST_LIVE_2026_05_22_\": 1}" | docker exec -i aaats-paper-crypto sh -c "cat > /app/data/share_equality_mismatches.json"'
sleep 65  # one scrape cycle
ssh aaats@100.95.126.39 'echo "{\"_TEST_LIVE_2026_05_22_|_TEST_LIVE_2026_05_22_\": 2}" | docker exec -i aaats-paper-crypto sh -c "cat > /app/data/share_equality_mismatches.json"'
sleep 120  # alert evaluation
# CHECK TELEGRAM CHAT 1946109268 for delivery
# Then revert:
ssh aaats@100.95.126.39 'echo "{}" | docker exec -i aaats-paper-crypto sh -c "cat > /app/data/share_equality_mismatches.json"'
```

**Pass criteria:**
- Telegram message received within 2 minutes of second write
- Message contains `_TEST_LIVE_2026_05_22_`
- Reverted JSON state confirmed empty

**Fail handling:** if alert silent, **STOP**. Trace through exporter → Prometheus → Grafana → Telegram per `docs/known_issues/` archive. No live flip until alert chain confirmed.

---

## Flip sequence (T-0)

### Step 1 — Rollback baseline

```bash
mkdir -p .rollback/2026-05-22_live_flip
ssh aaats@100.95.126.39 'cat /home/aaats/aaats/.env' > .rollback/2026-05-22_live_flip/env.pre
ssh aaats@100.95.126.39 'docker inspect aaats-paper-crypto --format "{{.Image}}"' > .rollback/2026-05-22_live_flip/image_sha.pre
ssh aaats@100.95.126.39 'cp /home/aaats/aaats/data/paper_trades.db /tmp/paper_trades_pre_live.db && ls -la /tmp/paper_trades_pre_live.db'
echo "MANIFEST: pre-live-flip baseline 2026-05-22 first tranche \$25" > .rollback/2026-05-22_live_flip/MANIFEST.txt
date >> .rollback/2026-05-22_live_flip/MANIFEST.txt
```

### Step 2 — Edit .env on box (atomic SCP per CLAUDE.md)

On workstation, prepare new `.env` with:

```
PAPER_MODE=False
LIVE_CAPITAL_USD=25.0
LIVE_TRANCHE_START=2026-05-22T00:00:00Z
LIVE_TRANCHE_NAME=tranche_1_25usd
# All other env vars copied verbatim from .env.pre
```

Upload via paramiko atomic swap (`.tmp + mv -f`) — use existing deploy script pattern.

### Step 3 — Restart paper-crypto into live mode

```bash
ssh aaats@100.95.126.39 'cd /home/aaats/aaats && docker compose -f deployment/docker-compose.yml restart aaats-paper-crypto'
sleep 30
ssh aaats@100.95.126.39 'docker logs aaats-paper-crypto --tail 50'
```

**Sanity checks immediately after restart:**
- Container shows "Up X seconds (healthy)" within 60s
- Logs show `PAPER_MODE=False` or equivalent live-mode startup banner
- First cycle attempts a real broker `get_account` call without auth errors
- `risk_engine_state.json` reads correctly (no zero or NaN equity)

If ANY sanity check fails, immediately:

```bash
# Revert .env
ssh aaats@100.95.126.39 'mv /home/aaats/aaats/.env.pre /home/aaats/aaats/.env'
ssh aaats@100.95.126.39 'docker compose -f deployment/docker-compose.yml restart aaats-paper-crypto'
```

### Step 4 — Watch first 4 cycles personally

**Operator stays at the terminal for first 4 cycles (~60min at 15-min cycle interval).**

For each cycle, verify in logs:
- Cycle banner with correct equity reading
- Strategy decisions (BUY/SELL/HOLD) printed
- If a BUY: real broker order ID returned (not paper sequence number)
- If a SELL: PnL within ±20% of expected paper-predicted PnL
- No exceptions
- Cycle completes within timeout

If 4 cycles run clean → step away. Daily digest scheduled task takes over monitoring.

---

## First 24h watchlist (auto-revert criteria)

Any one of these triggers immediate revert to paper:

| Signal | Threshold | Action |
|--------|-----------|--------|
| Reconcile HALT | 1 non-test event | Revert, file incident |
| Share-equality mismatch | any new entry with delta > $0.50 | Revert, file incident |
| Container restart | not auto-resolved within 5min | Revert if not back healthy by 10min |
| Realized PnL drawdown | > -$1.25 (-5% on $25) in any 4-hour window | Revert |
| Broker auth failure | not auto-resolved in 1 retry | Investigate before next cycle |
| Telegram alert delivery | silent for >30min when alert should fire | Investigate alert chain |

**Revert command (operator):**

```bash
ssh aaats@100.95.126.39 'cp /home/aaats/aaats/.env.pre /home/aaats/aaats/.env && docker compose -f deployment/docker-compose.yml restart aaats-paper-crypto'
```

After revert, file `docs/known_issues/2026-05-22_live_revert_<reason>.md` with:
- timestamp of revert
- last 100 lines of paper-crypto logs at revert time
- container state at revert (image SHA, RestartCount)
- root-cause hypothesis
- before re-attempting: write fix, soak 7d in paper, re-run this runbook

---

## T+7 escalation gate to $50

On 2026-05-29 (or 7 days after first live flip, whichever later), run:

```bash
ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python -m scripts.live_tranche_review --tranche tranche_1_25usd'
```

Expected output: a JSON report with:
- Trade count
- Realized PnL
- Max drawdown
- HALT events
- Share-equality state changes
- Predicted-vs-actual PnL per trade

**Escalate to $50 if ALL of:**
- Trade count >= 5 round-trips
- Realized PnL >= -$1.25 (i.e., better than -5%)
- 0 HALT events
- 0 share-equality mismatches
- Telegram alert chain verified via fresh synthetic test (PF3 re-run)
- Predicted-vs-actual PnL within ±20% on at least 80% of round-trips

**If any fail:** stay at $25, document gap, ship fix, re-evaluate next week.

A separate runbook will be drafted for the $50 tranche flip with same structure.

---

## What Claude does during live operation

- **Reads** logs and DB state via scheduled task (next section).
- **Drafts** daily digest summary in chat.
- **Drafts** incident write-ups if revert triggers.
- **Does NOT** touch trading code without explicit operator go-ahead.
- **Does NOT** execute the live flip or any trade-path commit.

---

## Daily digest scheduled task (Claude side)

Recommended setup — a scheduled task that runs each morning at 09:00 IST and posts a one-page digest:

- Trade count in last 24h
- Realized PnL in last 24h vs predicted-from-paper PnL
- Current open positions
- Max drawdown last 24h
- Any HALT events (should be zero)
- share_equality_mismatches.json state
- Container uptime + restart count
- Telegram alert health (last fire timestamp from Prometheus)

This task is created in the same session that the operator signs off on the live flip. Not created speculatively.

---

## Files to update after first 7d clean

- `data/deployment_decision.json` — refresh the auto-gate evaluation so future operators don't trip on stale "NOT READY"
- `MEMORY.md` (operator-assistant memory) — record the live-flip date, tranche size, T+7 outcome
- `docs/decisions/2026-05-22_live_readiness.md` — append outcome and link to T+7 review
- README.md — flip status badge from "Paper" to "Live (\$25 tranche 1)"

---

## What this runbook is NOT

- Not a substitute for the operator's personal eyes on the first 4 cycles
- Not a unified-ledger requirement gate (ledger Q1-Q4 work proceeds in parallel behind flag OFF)
- Not authorization to skip the 7-day soak between $25 → $50 → $100 escalations
- Not the runbook for $50 or $100 — those need separate documents with the actual observed-PnL data from the prior tranche feeding their gates
