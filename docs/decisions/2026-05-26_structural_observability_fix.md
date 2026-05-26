# Structural Observability Fix — "Stop the Bug Fires"

**Date:** 2026-05-26
**Status:** ACTIVE
**Sprint:** Cowork session — operator-driven request to stop recurring small breakages

## Context

Over the 2026-05-15 → 2026-05-26 window the AAATS paper-trading bot accumulated 15 filed bugs. Operator frustration peaked on the morning of 2026-05-26 with the report: `capital=$127.47` on `starting_equity=$200` and `realized_pnl=+$1.34` with zero open positions — an unexplained $73.87 deficit — plus no Telegram alerts for >24h. The operator's ask: stop patching one symptom at a time and do a proper root cause + permanent fix.

## Diagnosis

Investigation found:

1. **No real capital leak.** Every BUY/SELL path in code is symmetric: `execute()` line 1348/1404, C3 line 754/653, C6 line 455/379, C5b line 146/182, C1 stat_arb line 276. `pos["size_usd"]` is stored equal to `trade_usd` at entry, so the credit on exit matches the debit on entry. The operator's perceived deficit was **invisible open positions in C3 and C6 strategy state files that the autopush doesn't snapshot**.

2. **Autopush snapshot list incomplete.** `scripts/box/aaats-autopush-v3.sh` snapshots only 4 files (`paper_trades.db`, `paper_positions.json`, `paper_portfolio.json`, `stat_arb_state.json`). It does NOT snapshot `altcoin_reversion_state.json` (C3 positions), `bollinger_range_state.json` (C6 positions), `funding_arb_state.json` (C5b), `halt_state.json`, `strategy_halt_state.json`, `ledger_divergence_alerts.json`, or `share_equality_mismatches.json`. From origin/main's vantage, half the bot's state is invisible.

3. **DB cp silent failure.** `runtime/paper_trades.db` in the repo last modified 2026-05-24 14:51 (36h stale) while portfolio.json (also from autopush) is fresh. The `docker cp` for the DB is failing silently while the JSON cp succeeds. The autopush logs the failure but does not alert. Every monitoring layer reading from origin/main's DB (L1 heartbeat check, L7 activity-floor monitor) has been reading stale data.

4. **Telegram silence is mostly by design.** L1/L7 GitHub Actions fire only on outage; bot has been green; no alert needed. But L7's "is the bot trading?" check reads the 36h-stale DB and would falsely conclude "silent for 36h" — it should have fired. The absence of that alert means either GitHub secrets are missing OR L7 isn't running. Plus: operator expected SOMETHING (a daily heartbeat from outside the box), not silence.

5. **The dominant bug class is silent failure / no alert.** Catalog of the 15 filed bugs: 9 (60%) are "system degrades silently, no alert"; 5 (33%) are "dual source of truth"; 3 (20%) are schema/version drift; 1 (7%) is state atomicity. Patching individual symptoms doesn't close the class.

## Decision

Ship three changes addressing the class, not the symptoms:

### Fix A: Expanded autopush + DB freshness alert

`scripts/box/aaats-autopush-v3.sh` now snapshots **11 state files** (up from 4):

- Core 4 (existing): `paper_trades.db`, `paper_positions.json`, `paper_portfolio.json`, `stat_arb_state.json` — marked "hard" required.
- Strategy state (new): `altcoin_reversion_state.json`, `bollinger_range_state.json`, `funding_arb_state.json`, `momentum_state.json` — soft.
- Halt + alert state (new): `halt_state.json`, `strategy_halt_state.json`, `ledger_divergence_alerts.json`, `share_equality_mismatches.json`, `capital_invariant_alerts.json` — soft.

Plus a **DB freshness assertion**: track the `paper_trades.db` SHA-256 across ticks. 3 consecutive identical hashes (≈45 min of frozen DB) AND a healthy heartbeat → fire `aaats-cron-alert.sh` with 1h cooldown. Also a hard-snapshot-failure alert if any of the 4 core files fails to cp.

### Fix B: Capital invariant guard (Layer L11)

New functions in `execution/paper_trader.py`:

- `compute_capital_invariant(portfolio, market, positions, db_path, state_dir)` — computes `expected = starting_equity + DB.realized_pnl - all_open_notional` (strategy state + execute() directional) and returns the delta with a verdict.
- `assert_capital_invariant(...)` — writes `data/capital_invariant_alerts.json` on watch/warn/critical and logs at appropriate level. Does NOT auto-halt; operator judges first.

Wired into `trading/live_paper_runner.py` after the existing `_reconcile_portfolio_stats_from_db` call. Cross-container handoff to Grafana + Telegram follows the same pattern as L5.

Thresholds:
- ≤ $0.50 → OK (rounding noise floor)
- ≤ $2.00 → watch (within slip + fee band)
- ≤ $10.00 → warn
- > $10.00 → critical (log error, alert)

### Fix C: Daily Telegram digest workflow

New file `.github/workflows/daily-digest.yml`. Runs 06:05 UTC daily. Reads `runtime/*` from origin/main, composes a single message:

```
AAATS digest — 2026-05-27 06:05 UTC
Day 5 of D.5 soak

Crypto book: $127.47 cap (start $200, realized +$1.34)
Trades total: 79 (19W / 16L)
Trades 24h: 22 (PnL +$1.07)
Open positions: 4
  → C3:TON, C6:EDEN, C3:SAHARA, C3:MEGA

Halts: markets=['us', 'india'] strategies=none
Autopush: cycle_active (3min ago)
Capital invariant: ok (delta=$+0.12)
Ledger divergence: halt=none watch=none

Health: all clear
```

Operator gets explicit "all clear" daily. Silence ≠ OK; the missing morning message itself is the alert.

## Why this closes the class

Each of the 9 silent-failure incidents in the catalog would have been caught by at least one of A/B/C:

| Incident | Caught by |
|---|---|
| paper_positions_writer_drift | A (state files now visible) |
| state_persistence_paths_missing | B (open_notional reads from state) |
| btc_eth_ledger_drift | B + existing L5 |
| phantom_cash_drift_correction | B (invariant would have flagged the orphan) |
| cron_blackout_false_positive | A (heartbeat content already in L1, A makes DB-cp freshness visible too) |
| stash_hygiene_gap | C (digest would have surfaced anomaly) |
| pager_5plus_restart_not_firing | C (digest shows halt status daily) |
| share_equality_alert_chain | A (alerts file now in snapshot) |
| 2026-05-26 morning $73.87 perception | A (positions visible) + B (verdict tells operator "ok") + C (next morning's digest confirms) |

## Deploy mechanism

`tools/operator/deploy_structural_fix_2026_05_26.py` — single-script paramiko deploy. Atomic .tmp swaps; container rebuild for B; autopush file lands on host directly; workflow lands on push to origin/main. Backup baseline written to `/home/aaats/bin/aaats-autopush.sh.bak-<ts>` and `*.py.bak-<ts>` on the box before each overwrite.

## Non-decisions

- **Did NOT** add auto-halt on L11 critical. Capital drift can have legitimate causes (mid-cycle recovery, manual reset); auto-halting on the invariant would risk locking the operator out of a healthy bot during the D.5 soak. Operator judges.
- **Did NOT** unify the dual-ledger debt (positions dict vs strategy state files vs trade DB). That's a separate, larger sprint (memory `aaats_dual_equity_ledger_debt.md`); doing it during D.5 soak is high-risk. The invariant in B detects the symptom of dual-ledger drift even without unifying them.
- **Did NOT** rewire Telegram alert chain for trade-fill notifications. The user's "I haven't received Telegram" was mostly the green-state silence + the missing digest, not the per-trade `send_alert` chain. If trade-fill notifications turn out to also be broken, that's a follow-up.

## Follow-ups

- **2026-05-27 06:05 UTC** — first daily digest should land. If it doesn't, check repo secrets `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` + variable `LIVENESS_ENABLED`.
- **Post-soak (2026-06-22+)** — revisit dual-ledger unification once invariant has been quiet for 30 days.
- **If L11 critical fires** during soak — operator decides between (a) halt + investigate (run kill.py crypto halt) or (b) check `data/capital_invariant_alerts.json` for the breakdown and judge whether it's a real leak vs a recovery artifact.

## References

- `scripts/box/aaats-autopush-v3.sh` (updated)
- `execution/paper_trader.py` (L11 block at EOF)
- `trading/live_paper_runner.py` (L11 wire after line 2250)
- `.github/workflows/daily-digest.yml` (new)
- `tools/operator/deploy_structural_fix_2026_05_26.py` (new)
- `.rollback/2026-05-26_structural_fix/MANIFEST.txt` (new)
