# Next Claude Code session prompt (session 4)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-22 (post session 3 — [0] heartbeat reader + [1] box deploy of D.1/D.3/heartbeat + [2] B.2 C3 + [3] D.2 watchdog code + [4] A.1 design all shipped).

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, session 4. Session 3 shipped everything in its prompt
(legacy heartbeat reader removal, box deploy of D.1+D.3+heartbeat-reader,
B.2 C3 PARAM-TUNE + symbol-halt patch on box, D.2 watchdog code+tests,
A.1 state-isolation design memo). Status logs at
docs/decisions/2026-05-22_live_flip_rebuild_plan.md and
docs/decisions/2026-05-21_track_d_reliability_addendum.md have full
session 3 ship reports under "2026-05-22 (session 3)". PF1 score moved
from 80.6% to 100.2%; "Infrastructure Uptime" cleared from blockers.
Remaining PF1 blockers are real strategy state: Win Rate 28.3%, Drawdown
-33.4% (peak $131.32, last_equity ~$87.45 per risk_engine_state.json).

Surfaced from session 3 (folded into session 4 scope, do NOT re-investigate from scratch):
- KILL-TRIGGER BAND-AID active: trading/live_paper_runner.py:1881 was set
  back to halt_on_critical=False this session (operator-approved). Pre-deploy
  the reconciler HALTed every cycle on a real ~$7 BTC/ETH dust drift
  (symbol_present_in_only_one_source) — restart-loop. Reconciler still WARNs
  every cycle but doesn't break the loop. Real root cause is a ledger writer
  mismatch (BTC/ETH show in one ledger but not the other); proper fix is in
  the unified-ledger sprint, NOT this session. Until then the band-aid stands.
- D.2 watchdog is CODE-COMPLETE + TESTS green but NOT yet on box. The compose
  service mounts /var/run/docker.sock (privileged), which is operator-gated.
  This session's job: get operator approval, then SCP + rebuild aaats-watchdog,
  then run the end-to-end smoke (kill aaats-paper-crypto → watchdog detects →
  Telegram fires → restart). Spec in docs/decisions/2026-05-21_track_d_reliability_addendum.md
  §"Phase D.2".
- A.1 state-isolation IMPLEMENTATION is queued (memo at
  docs/decisions/2026-05-22_state_isolation_design.md). Three things needed:
  (a) operator review of the compose change (per-mode named volumes —
  state-crypto-paper, state-crypto-live), (b) the one-time migration script
  scripts/migrate_state_to_per_mode.sh, (c) the risk/engine.py:_state_file_path()
  refactor with tests (test list in the memo).

Read first, in this order:
1. docs/decisions/2026-05-21_autonomy_contract.md — full technical autonomy still active.
2. docs/decisions/2026-05-22_live_flip_rebuild_plan.md — read the "Status log" entry
   for 2026-05-22 (session 3) AND the B.1 triage table immediately above it.
3. docs/decisions/2026-05-21_track_d_reliability_addendum.md — read the
   2026-05-22 (session 3) entry for D.2 status + cross-cutting findings.
4. docs/decisions/2026-05-22_state_isolation_design.md — A.1 memo (full text).
5. CLAUDE.md — deploy discipline still binding.

Goal of this session: execute (in order of leverage):
  [0] D.2 watchdog box deploy — operator approval of /var/run/docker.sock mount,
      then SCP + rebuild aaats-watchdog, then end-to-end smoke.
  [1] A.1 state-isolation IMPLEMENTATION — code edit at risk/engine.py +
      compose-level per-mode named volumes + one-time migration script + tests.
  [2] B.2 paper-shadow validation — 7-day backtest OR paper-shadow comparison
      of pre/post C3 P&L curves. The C3 patch is deployed; this measures it.
  [3] D.4 design memo — daily digest spec (format LOCKED in Appendix A of
      the Track D addendum; this is the implementation memo).
  [4] BTC/ETH ledger drift triage memo — root-cause investigation memo at
      docs/known_issues/2026-05-23_btc_eth_ledger_drift.md. The band-aid
      (halt_on_critical=False) is reversible in one line once the writer
      side is fixed. This memo identifies WHERE to fix; the actual fix is
      in the unified-ledger sprint.

[0] D.2 watchdog box deploy:
  - First action: ASK OPERATOR for sign-off on the /var/run/docker.sock
    mount. The compose entry was committed in session 3 but the deploy
    requires an operator-gate per the autonomy contract (privileged
    socket = "shared infrastructure" scope).
  - On approval: paramiko SCP for:
      health/__init__.py, health/watchdog.py
      deployment/Dockerfile.watchdog
      observability/alerts.py (verify on box; not modified this session)
    Then on box: cd /home/aaats/aaats/deployment && docker compose up -d
    --build aaats-watchdog (no --no-deps because new service has no
    siblings depending on it).
  - End-to-end smoke (operator-coordinated):
      docker stop aaats-paper-crypto
      # wait 45min for stale threshold (or override WATCHDOG_CYCLE_INTERVAL_SEC=10 for test)
      # observe Telegram + auto-restart
    Repeat 4× to trigger the escalation path.
  - Exit: aaats-watchdog status=running for >24h; one synthetic
    restart-recovery cycle observed in logs.

[1] A.1 state-isolation implementation:
  - File: risk/engine.py:44-46. Replace `STATE_FILE = Path(...)` with
    `_state_file_path()` helper per the memo §"Code change (one file, one block)".
  - Compose: deployment/docker-compose.yml. Per-mode named volumes
    (state-crypto-paper, state-crypto-live) + AAATS_RISK_STATE_DIR env
    interpolation. Per the memo §"Compose change". REQUIRES operator
    review.
  - Migration: scripts/migrate_state_to_per_mode.sh — one-time copy from
    state-crypto to state-crypto-paper.
  - Tests: tests/test_state_isolation.py per the memo §"Test plan" table
    (5 cases). All must be green before the compose edit lands on box.

[2] B.2 paper-shadow validation:
  - The C3 patch is deployed (verified session 3). Now measure it.
  - Option A: backtest. If scripts/backtest_c3_param_sweep.py exists or can
    be built quickly, run pre-patch (BTC_DOM_FAST_RISE not wired,
    no denylist) vs post-patch on the last 30d of trades.
  - Option B: paper-shadow. Wait 7d, compute realized P&L of post-patch
    C3 trades, compare against the session-1 -$5.63/9d baseline.
  - Exit: post-patch realized P&L documented in a follow-up memo under
    docs/known_issues/2026-05-23_strategy_c3_post_b2.md.

[3] D.4 daily digest implementation memo (NOT code this session — memo only):
  - Format LOCKED in docs/decisions/2026-05-21_track_d_reliability_addendum.md
    Appendix A. Memo identifies: data sources per section (paper_trades.db,
    state files, strategy_exception_state.json, watchdog_heartbeat.json),
    cron-vs-scheduled-task decision, dry-run plan, Telegram destination.
  - Exit: docs/decisions/2026-05-23_daily_digest_design.md.

[4] BTC/ETH ledger drift triage:
  - Read scripts/reconcile_intracycle.py — find the source of
    "symbol_present_in_only_one_source" detection.
  - Identify the writer mismatch: which ledger reports BTC/USDT
    0.00009052 (= ~$7) and which reports 0? Likely sources:
      - paper_trades.db (action records)
      - data/paper_positions.json (snapshot)
      - per-strategy state files (altcoin_reversion_state.json etc.)
      - data/paper_portfolio.json
  - Document at docs/known_issues/2026-05-23_btc_eth_ledger_drift.md: which
    writer is leaking, why, and the one-line fix path in the unified-ledger
    sprint. NO behavior change this session (autonomy contract — ledger
    writer changes are doctrine-adjacent).

Constraints (unchanged from sessions 1+2+3):
  - No SCP deploy from dirty tree.
  - `git pull --rebase` BEFORE every push. Auto-cron on box pushes
    runtime/ + data/ + logs/ snapshots every 15 min (CLAUDE.md update
    from session 3: cron touches runtime/ too, not just data/+logs/).
    Rebase is usually conflict-free.
  - Push to GitHub at end of session.
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Keep paper-crypto running. Use `--no-deps aaats-paper-crypto`.
  - PAPER_MODE env var stays unused (A.1 implementation may activate
    SYSTEM__TRADING_MODE-driven paths but PAPER_MODE specifically is
    deferred further).

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md
    ([0]+[1]+[2] ship reports).
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md
    ([0]+[3] D.2 deploy + D.4 memo).
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with session 5 prompt.
  - Commit + push.
  - Ping operator on: D.2 box-deploy approval ([0]), A.1 compose-change review
    ([1]), or kill-switch events (drawdown more negative than -30%, share-equality
    delta > $0.50, container failing to start). Otherwise no ping needed.

Start with [0]: ASK OPERATOR for the docker.sock approval. While that's
pending, work on [1] state-isolation tests + risk/engine.py refactor
(workstation-only, no operator gate needed for that prep). Then re-check
operator decision on [0]; if approved, deploy + smoke. Then [2]/[3]/[4]
are all memo-only-this-session work, parallel-safe.

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents may hit
Write-tool permission denials. If you delegate, instruct subagents to
return content in their reply, not call Write directly.
```
