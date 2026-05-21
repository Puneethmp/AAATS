# 2026-05-22 NO-GO — live-flip mechanism not functional

**Decision reversed 2026-05-21 evening (operator).** This document was authored
as a PROVISIONAL GO. Pre-flight investigation discovered the live-flip
mechanism is non-functional (see
docs/known_issues/2026-05-21_live_flip_mechanism_gaps.md). The $25 first
tranche on 2026-05-22 is CANCELLED. The rebuild sprint is the prerequisite.

Original GO content preserved below for sprint-planning reference. The
"three pre-flight verifications", "auto-revert criteria", and "execution
amendment" sections all become void once the live mechanism is rebuilt and
require redrafting from the new architecture.

---

# Live-Capital Readiness Decision — 2026-05-22 doctrine floor

**Date authored:** 2026-05-21 (T-1 to doctrine minimum live date)
**Decision authority:** operator-assistant draft; awaiting Puneeth sign-off
**Status:** **PROVISIONAL GO with $25 first tranche** (not the full $100), conditional on three pre-flight verifications listed below
**Reverses earlier session draft:** an earlier NO-GO call was based on 5-day-stale memory. Live audit on 2026-05-21 revealed G1/G2/G3 closed, B' deployed, paper-crypto soaking clean. The infra blockers cited in the earlier draft are CLOSED. See "Audit timeline" at the bottom.

---

## Decision

### Go live with $25 capital on 2026-05-22, NOT $100.

Doctrine permits $100 initial live (`aaats_locked_doctrine_2026_05_14.md`). We are explicitly halving the first tranche because:

1. The first 24-48 hours of live trading surfaces a **different class of bug** than paper trading can ever show: real broker partial fills, real fee asymmetry, real funding-rate accruals on perp legs, real network timeout retries against the broker API.
2. Paper-crypto has soaked clean post-G1-flip for 5 cycles. That's evidence the infra holds. It is **not** evidence the broker integration holds.
3. Halving the first tranche halves the worst-case drawdown if a real-broker-class bug surfaces (≈$5 max single-trade loss instead of ≈$10 on a -10% position).
4. Capital doesn't compound on the discount: if 7-day soak is clean, escalate to $50, then $100. The doctrine's monthly cadence ($50/mo) means we're not behind any monetization clock.

### Tranche escalation gates (each independently verifiable):

| Tranche | Start | Duration | Gate to advance |
|---------|-------|----------|----------------|
| $25 | 2026-05-22 | 7 days | 0 reconcile HALTs, equity ≥ -3% drawdown, share_equality_mismatches.json stays empty |
| $50 | 2026-05-29 | 7 days | Same + 5+ live SELL roundtrips with PnL within ±20% of paper-predicted PnL |
| $100 | 2026-06-05 | open | Same + first weekly review free of regressions; matches the locked doctrine's $100 floor |

### Auto-revert criteria (any one triggers immediate paper-only revert):

- **Any** non-test reconcile HALT
- Share-equality mismatch with delta > $0.50
- Drawdown deeper than -5% on $25 tranche, -7% on $50, -10% on $100
- Any container restart that doesn't come back healthy within 5 minutes
- Broker auth failure not auto-resolved on retry

---

## What was blocking yesterday (audit corrections)

### CLOSED — re-affirmed during 2026-05-21 audit:

| Gate | Status | Closure ref |
|------|--------|-------------|
| G1 — `halt_on_critical=False` | CLOSED 2026-05-20 | commit `d1b7feb` flipped to True; soaked 5 cycles clean |
| G2 — Scanner modules missing from origin/main | CLOSED 2026-05-15 | feat(markets) commit chain |
| G3 — Image built from partial host build context | CLOSED 2026-05-16 | RUNTIME-LATENT rsync + rebuild |
| B' — Kill-switch helper for C3/C6 | CLOSED 2026-05-20 | `fb59128` apply_kill_switch_gate, soaked clean |
| OBS — CYCLE_SUMMARY observability | CLOSED 2026-05-20 | `c9e7172`, gated-vs-never-dispatched now disambiguated |
| Reconcile clean (paper-crypto) | CONFIRMED 2026-05-20T17:54Z audit | `share_equality_mismatches.json: {}` post-deploy |

### NOT closed but NOT blocking live (existing strategies):

| Item | Status | Why not blocking |
|------|--------|------------------|
| Q1-Q4 ledger spec | Awaiting sign-off (recommendations doc shipped 2026-05-21) | Blocks strategy #13 + C5b re-enable; does **not** block 4 currently firing strategies (C1/C2/C3/C6). |
| Dust threshold $0.25 (TEMP) | Awaiting unified ledger | Static across two weeks; not introducing new residuals post-`_record` fix. |
| C5b funding_arb HALTED at source | Intentional | Halted by design pending ledger; not a blocker for spot strategies. |
| `deployment_decision.json` stale | Last-evaluated 2026-05-15 | Was based on 17-trade snapshot; box has done **~280 trades** since (auto-committed via `runtime/paper_trades.db`). Re-run gate before deploy. |

---

## Three pre-flight verifications before pushing the live switch

These **must** be done by operator at the box, in order, immediately before flipping live. None require Claude:

### PF1 — Re-run deployment_decision evaluation

```bash
ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python -m scripts.evaluate_live_readiness'
```

Expected: `allowed: true`, `readiness_score >= 90`, no blockers. If `total_trades < 50` or any other blocker fires, **abort and investigate**. The 2026-05-15 snapshot had 17 trades; current paper-crypto trade count is unknown to workstation but expected to be well over 50 based on 18.7 trades/day velocity in the v6 sibling.

### PF2 — Confirm clean reconcile state for last 24h

```bash
ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python -c "
import sqlite3
conn = sqlite3.connect(\"/app/data/paper_trades.db\")
print(\"trades last 24h:\", conn.execute(\"SELECT COUNT(*) FROM paper_trades WHERE timestamp >= datetime(\\\"now\\\", \\\"-24 hours\\\")\").fetchone()[0])
print(\"open positions:\", conn.execute(\"SELECT COUNT(*) FROM paper_trades WHERE action=\\\"BUY\\\"\").fetchone()[0] - conn.execute(\"SELECT COUNT(*) FROM paper_trades WHERE action=\\\"SELL\\\"\").fetchone()[0])
"'

ssh aaats@100.95.126.39 'cat /home/aaats/aaats/data/share_equality_mismatches.json'
```

Expected: trades >= 5, share_equality_mismatches.json = `{}` (or contains only TON/FET historical artifacts known to be silenced by dust filter). If counter shows any **new** symbol or delta > 0 in last 24h, **abort**.

### PF3 — Verify Telegram alert chain end-to-end

Trigger synthetic `_TEST_LIVE_` warn per CLAUDE.md recipe:

```bash
ssh aaats@100.95.126.39 'echo "{\"_TEST_LIVE_|_TEST_LIVE_\": 1}" > /home/aaats/aaats/data/share_equality_mismatches.json'
# wait 60s for scrape, then increment to 2 to give increase()[1h] a delta:
ssh aaats@100.95.126.39 'echo "{\"_TEST_LIVE_|_TEST_LIVE_\": 2}" > /home/aaats/aaats/data/share_equality_mismatches.json'
# wait for Grafana alert evaluation cycle (60s)
# confirm Telegram message received
# revert:
ssh aaats@100.95.126.39 'echo "{}" > /home/aaats/aaats/data/share_equality_mismatches.json'
```

Expected: Telegram delivery to chat `1946109268` within 2 minutes. If silent, **abort and debug alert chain** — going live without a working alert path is unacceptable.

---

## Architecture: paper-crypto vs aaats-engine (sibling v6 stack) — DO NOT CONFUSE

This is load-bearing context that bit during the 2026-05-21 audit:

| Container | Purpose | Live-readiness relevance | Current state (2026-05-20T18:00Z auto-commit) |
|-----------|---------|-------------------------|----------------------------------------------|
| **aaats-paper-crypto** | The 5-strategy bot under live-readiness review (C1/C2/C3/C5b-halted/C6) | **PRIMARY** — this is what goes live | Healthy, RestartCount=0, cycle 4 of OBS image, share_equality empty |
| **aaats-engine** | Parallel v6 stack research/research-replay system | **IRRELEVANT** to live-capital decision; runs in parallel, do not stop | HALTED on -15.5% crypto drawdown, -$93.88 realized PnL on $120 |

**Hazard:** runtime/paper_trades.db on the workstation (and on origin/main via auto-commits) is the **v6 engine's** database, NOT paper-crypto's. The 2026-05-21 audit briefly mistook v6's loss for paper-crypto's. Going forward:

- Live-readiness questions → look at `aaats-paper-crypto`'s container state and its DB on the box (`/app/data/paper_trades.db`).
- v6 engine drawdown → separate problem, separate doc (`docs/known_issues/2026-05-21_aaats_engine_v6_halt.md` filed today).

---

## Live deploy — operator-only steps (Claude does not execute live flip)

Per doctrine and per the "Financial actions" rule in the operator notes, Claude does not execute trades or move money. The live-flip is operator-only.

1. **Operator** completes PF1 → PF2 → PF3 above.
2. **Operator** edits `.env.live` to set `PAPER_MODE=False` and `LIVE_CAPITAL_USD=25.0` (do NOT use $100).
3. **Operator** runs the live-deploy script (existing pattern):
   ```bash
   python scripts/deploy_live_flip.py --tranche 25 --confirm
   ```
4. **Operator** monitors first 4 cycles personally before stepping away — paper soak is not a substitute for the human eye on the first live cycles.
5. After 7 days clean, **operator** runs the same script with `--tranche 50`.

---

## What Claude does between live-flip and 7-day re-evaluation

- **Nothing in the trade path.** Read-only access to runtime logs only.
- **Daily digest** of: trade count, realized PnL, max drawdown, any HALT events, share-equality state. Delivered as a scheduled task (see `scheduled-tasks` create below).
- **Q1-Q4 ledger work** can proceed in parallel because it stays behind `USE_UNIFIED_LEDGER` flag OFF; no risk to live capital.

---

## What success looks like on 2026-05-29 (T+7 review)

| Metric | Target | Auto-revert if |
|--------|--------|----------------|
| Trade count (live) | >= 5 round-trips | < 2 round-trips (insufficient signal) |
| Realized PnL (live, $25 tranche) | >= -$1.25 (i.e., -5%) | < -$1.25 |
| Reconcile HALT events | 0 | >= 1 non-test |
| Share-equality mismatches | 0 new entries | any new entry with delta > $0.50 |
| Container restarts not auto-resolved | 0 | >= 1 unresolved |
| Telegram alert delivery confirmed | yes (per PF3 weekly re-test) | no |

If all green: escalate to $50 tranche. If any red: revert to paper, document the surfaced bug class, fix, re-soak 7d, re-attempt.

---

## Audit timeline (2026-05-21 session, sequence of corrections)

| Time | Finding | Effect on decision |
|------|---------|---------------------|
| Session start | Memory said G1 open, NO-GO recommended | Initial draft was NO-GO |
| `git log` review | Commit `d1b7feb 2026-05-20 fix(risk): enable halt_on_critical` found | G1 actually CLOSED |
| `docs/decisions/2026-05-20_post_phase0_audit.md` read | Confirms G1+B'+OBS all soaked clean 2026-05-20 | NO-GO collapses; reframes as live-ready |
| `runtime/STATUS.md` + `engine.log` review | v6 aaats-engine HALTED at -15.5% drawdown | Initially misread as paper-crypto failure |
| Container heartbeat audit | aaats-paper-crypto separate, healthy | v6 problem is sibling, not the live-readiness path |
| `data/deployment_decision.json` review | Says "17/50 trades NOT READY" but dated 2026-05-15 | Auto-gate is stale; PF1 must re-evaluate |
| `runtime/paper_trades.db` count | 280 trades, 18.7/day velocity | 50-trade gate trivially cleared even if paper-crypto's DB is 1/3 of v6's volume |

**Lesson preserved (memory-worthy):** post-compact / new-session, do a `git log --oneline -20 | grep -v auto:` and read the latest decision doc BEFORE acting on any memory file older than 48h. Memory at 5+ days is point-in-time; decisions doc is current truth. Filed in memory as guidance.

---

## Sign-off prompts (paste one back)

- **"GO $25 tomorrow, run the three pre-flights"** → I'll draft the operator-side runbook + the daily-digest scheduled task
- **"Defer 7 days, finish ledger first"** → I'll write the extend-paper memo and re-target 2026-05-29
- **"Go full $100 tomorrow"** → I'll push back hard once with the reasoning above, then defer to your call
- **"Other"** → Tell me what concerns I haven't addressed

---

## Tranche 1 outcome (2026-05-21)

NOT EXECUTED. NO-GO declared after pre-flight investigation revealed:
- risk state inherits paper drawdown (-13.1%) across mode boundary
- PAPER_MODE env is not read by any consumer
- SYSTEM__TRADING_MODE is compose-hardcoded and validate-gated to paper
- no live trade loop exists

Workstreams A (docs), B1/B2/B3 (unified ledger), C (live-flip scripts) shipped
on 2026-05-21 and remain valid as foundation work. The flip scripts in
scripts/ are kept for reference but will be rewritten in the rebuild sprint
once the live trade loop exists for them to flip into.
