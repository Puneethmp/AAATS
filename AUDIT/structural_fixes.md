# Structural Fixes — Fix Log (Phase 2)

> Forensic-audit mandate, 2026-06-10. All changes are repo-side (no container
> redeploy this session). Each fix ships with tests. Items needing a box deploy
> are marked **[STAGED]** and listed at the end.

## FIX 1 — Honest cost model (the headline Phase-0 defect)

**Defect:** the live PnL path (C1/C3/C6) records gross PnL from RAW prices — zero
fees, zero slippage, zero funding. The ledger was optimistic; the mandate forbids
gross-only reporting.

**Fix:** new pure, tested cost layer + honest re-pricer + no-trade baseline:
- `analytics/cost_model.py` — single source of truth for fees/slippage/funding
  (Binance VIP-0 rates mirroring `execution/fill_model.py`).
- `analytics/ledger_repricer.py` — re-reads `paper_trades.db`, re-prices every
  realized event net of costs, buckets it (SIGNAL/COST/RISK/WIN), computes the
  cost ratio, and compares to the no-trade baseline.
- `analytics/ledger_repricer.no_trade_baseline()` / `buy_and_hold_pnl()` — the
  permanent benchmark every strategy is measured against.

**Tests (before/after):** `tests/test_cost_model.py` (11) + `tests/test_ledger_repricer.py` (7).
Key assertions: a $0.10 gross winner flips to the COST bucket; net is always below
gross when costs apply; the no-trade baseline is $0; "beats no-trade" only when net>0.

**Validation against the real ledger:** reproduces Phase 0 exactly — gross −$2.27,
**net −$13.01**, beats_no_trade **NO**, cost_ratio **16.4** (costs are 16× the
winners' gross profit). This is now reproducible from one command:
`python -m analytics.ledger_repricer runtime/paper_trades.db`.

## FIX 2 — ML model-health guard (the "ML gate" item)

**Investigation result:** the prior "XGBoost blocks ALL signals" defect is **NOT
reproduced**. `_score_ml` returns **0.55 (neutral pass)** on a missing/erroring
model (`live_paper_runner.py:1570,1621`); the gate only blocks `conf<0.40` from a
live model. The real problems are the inverse:
1. The model is **stale** (trained 2026-05-07 → 33.9 days old) and **near-random**
   (val_acc **0.5508**).
2. The gate only applies to the majors/`execute()` path — **C3/C6 (the bulk of
   trades) bypass it entirely.** The "intelligence" stack gates a path that barely
   trades while the losing strategies run ungated.

**Fix (repo-side):** `ml/model_health.py` — staleness + accuracy-floor guard so the
defect can't recur silently (the mandate's "alert if labels exceed max age",
generalized to model freshness + accuracy). `health_report()` on the real model
returns `trustworthy=false, reasons=["stale (age=33.9d > 7.0d)"]`.

**Tests:** `tests/test_model_health.py` (6) — fail-closed on missing `trained_at`,
sub-floor accuracy fails, current on-disk model is flagged untrustworthy.

**[STAGED] recommendation:** per the mandate ("retrain walk-forward OR remove the
gate"), and given the program-wide no-edge verdict, **remove the ML gate** — it is
dead weight (stale, near-random, and bypassed). This is a live-runner edit →
deploy-coupled.

## FIX 3 — HMM regime staleness (investigation)

**Result:** already handled in code — `_regime_is_stale()` + 4h refit cadence +
rule-based fallback (`live_paper_runner.py:516,533,545`). Like the ML gate, it only
weights votes on the majors path and does not gate C3/C6. No code change needed;
the `model_health` pattern (FIX 2) is the monitoring hook if HMM artifacts are ever
persisted.

## FIX 4 — Public-repo log-leak (HIGH, active) — FIXED without deploy

**Defect:** the box autopush writes `docker logs --tail 500` of both containers to
`runtime/{engine,paper_crypto}.log` (`scripts/box/aaats-autopush-v3.sh:179-180`),
which is `git add runtime/`'d and pushed to the **PUBLIC** repo `Puneethmp/AAATS`
every 15 minutes. A future traceback containing an API key would be exposed.

**Current-snapshot scan:** no secret patterns found in the presently-committed logs
(no confirmed leak), but the vector is live.

**Fix:** `git rm --cached runtime/{engine,paper_crypto}.log` + `runtime/*.log` added
to `.gitignore`. Because the box does `git reset --hard origin/main` then
`git add runtime/`, the ignore **propagates automatically on the next cron cycle —
no box deploy required.** `check_engine.py` reads logs via `docker logs`, not these
files, so nothing breaks.

**[STAGED] operator follow-ups:**
1. Scan **full git history** (not just HEAD) for any past leaked secret; if found,
   rotate the key and scrub history (git-filter-repo / BFG).
2. Decide whether to keep auto-push at all. It feeds L1/L7/L10 liveness monitors
   (GitHub Actions read origin/main), so removing it wholesale blinds monitoring.
   The log-tail removal already closes the security hole while keeping monitoring.

## [STAGED] — needs an explicitly-confirmed box deploy

| Item | Why staged |
|---|---|
| Remove ML gate from runner (FIX 2) | live-runner edit; only takes effect on redeploy |
| Delete C5b/C2 modules + runner imports (see prune_log) | live-runner edit; repo/box must stay in sync |
| Demote C1/C3/C6 to no-trade | the only honest posture given no edge; needs runner change + deploy |
| Wire `analytics.cost_model` into the live record path | makes the live ledger net-of-cost at write time (today it's re-priced post-hoc) |
| Full git-history secret scan + key rotation | operator action |
