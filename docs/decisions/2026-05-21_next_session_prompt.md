# Next Claude Code session prompt (session 5)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-22 (post session 4 — [0] D.2 box deploy + [1] A.1 implementation (workstation) + [2] B.2 memo + [3] D.4 memo + [4] BTC/ETH ledger drift memo all shipped).

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, session 5. Session 4 shipped everything in its prompt:
D.2 watchdog box deploy with smokes A-F green (image sha256:4a27584eb76f,
incl. 2 Dockerfile/compose bug fixes), A.1 state-isolation IMPLEMENTATION
on workstation (risk/engine.py refactor + 6/6 tests + compose change +
migration script — operator-gated for box), and three memos (B.2 protocol
locked for 2026-05-29 re-eval, D.4 daily-digest design with dispatch via
the watchdog poll loop, BTC/ETH ledger drift root-cause identified as a
2-bug convergence in the reconciler with Option A one-line fix queued).
Status logs at docs/decisions/2026-05-22_live_flip_rebuild_plan.md and
docs/decisions/2026-05-21_track_d_reliability_addendum.md have full
session 4 ship reports under "2026-05-22 (session 4)".

PF1 score remained at 100.2% post-session-4 (no D.2 deploy reduces PF1
blockers; the two remaining blockers are real strategy state: Win Rate
28.3%, Drawdown -33.4%). The drawdown reflects mark-to-market on open C3
positions; B.3 soak is what fixes that, not a code change.

Surfaced from session 4 (folded into session 5 scope, do NOT re-investigate from scratch):
- KILL-TRIGGER BAND-AID still active: trading/live_paper_runner.py:1881
  remains halt_on_critical=False. Root cause is now identified — see
  docs/known_issues/2026-05-23_btc_eth_ledger_drift.md. Option A in that
  memo is a one-line patch to scripts/reconcile_intracycle.py:323 that
  excludes C1_stat_arb from Source B (parity with the existing C5b
  exclusion). Re-enabling halt_on_critical=True is safe once Option A is
  in place.
- A.1 state-isolation is WORKSTATION-COMPLETE: risk/engine.py refactor
  shipped, 6/6 tests green, compose change drafted, migration script
  drafted. Operator has NOT approved the compose change yet (the per-mode
  named-volume layout is "shared infrastructure" scope per the autonomy
  contract). Session 5 picks up at: ask operator → if approved, run the
  box deploy sequence in docs/decisions/2026-05-22_state_isolation_design.md
  §"Status log" 2026-05-22 (session 4).
- D.4 daily digest is DESIGNED, not implemented. Spec is in
  docs/decisions/2026-05-23_daily_digest_design.md. ~1 Sonnet session to
  build: monitoring/daily_digest.py + data/digest_log.json + watchdog
  loop wiring + new cycle_log SQLite table written from
  trading/live_paper_runner.py next to the heartbeat write.
- B.2 paper-shadow validation is AWAITING DATA: 7-day window from the
  patch deploy ends 2026-05-29T15:00Z. Re-evaluate per the locked protocol
  in docs/known_issues/2026-05-23_strategy_c3_post_b2.md.
- Watchdog is running on box from session 4. data/watchdog_heartbeat.json
  is updated every 60s by the box; observe last_decision==ok as proof of
  liveness.

Read first, in this order:
1. docs/decisions/2026-05-21_autonomy_contract.md — full technical autonomy still active.
2. docs/decisions/2026-05-22_live_flip_rebuild_plan.md — read the "Status log" entry
   for 2026-05-22 (session 4) AND the B.1 triage table immediately below it.
3. docs/decisions/2026-05-21_track_d_reliability_addendum.md — read the
   2026-05-22 (session 4) entry for D.2-deploy + D.4-memo status.
4. docs/known_issues/2026-05-23_btc_eth_ledger_drift.md — root-cause memo,
   incl. the three fix options.
5. docs/decisions/2026-05-22_state_isolation_design.md — A.1 design + the
   session-4 implementation status with the box deploy sequence.
6. docs/decisions/2026-05-23_daily_digest_design.md — D.4 implementation spec.
7. docs/known_issues/2026-05-23_strategy_c3_post_b2.md — B.2 measurement
   protocol (skip if before 2026-05-29).
8. CLAUDE.md — deploy discipline still binding.

Goal of this session: execute (in order of leverage):
  [0] BTC/ETH ledger drift Option-A fix + re-enable halt_on_critical=True.
      One-line reconciler patch (add C1_stat_arb to Source B's exclusion
      SQL) + one-line revert of the band-aid + verification cycle.
  [1] A.1 box deploy — ASK operator for the compose-change review FIRST.
      On approval: SCP docker-compose.yml + risk/engine.py + the
      migration script, run the migration on box, rebuild aaats-paper-crypto,
      verify the post-deploy log line confirms the paper peak was preserved.
  [2] D.4 daily digest IMPLEMENTATION — build the module, the test suite,
      the watchdog loop wiring, and the cycle_log table. Dry-run once on
      workstation, once on box, then enable live sends.
  [3] B.2 evaluation (only if today >= 2026-05-29) — run the queries in
      the memo, compare against pass/fail criteria, close or extend.
  [4] D.5 soak day-1 begin — the first day the daily digest fires with
      Action needed: NONE.

[0] BTC/ETH ledger drift Option-A fix:
  - File: scripts/reconcile_intracycle.py:323. Change:
      "WHERE strategy != 'C5b_funding_arb' "
    to:
      "WHERE strategy NOT IN ('C5b_funding_arb', 'C1_stat_arb') "
  - File: trading/live_paper_runner.py:1881. Change:
      halt_on_critical=False
    back to:
      halt_on_critical=True
  - Add a regression test at tests/test_reconciler_c1_exclusion.py that
    seeds a synthetic C1 BUY of BTC + SELL of ETH in a tmp paper_trades.db
    and asserts the reconciler PASSES (no issues, not HALTed).
  - SCP both files to box via a new deploy script
    scripts/deploy_session5_reconciler_c1_exclusion.py (model on
    deploy_session4_d2_watchdog.py).
  - On box, observe one full cycle after deploy: reconciler should report
    "Reconciliation clean | checked=N positions" without any HALT-severity
    issues. The C1 BTC+ETH legs should now be invisible to Source B.
  - Exit: halt_on_critical=True active on box, reconciler running clean,
    one cycle's audit-trail entry confirming.

[1] A.1 box deploy:
  - First action: ASK OPERATOR for the compose-change review. The diff to
    show: deployment/docker-compose.yml's aaats-paper-crypto service now
    mounts state-crypto-paper + state-crypto-live (instead of the legacy
    state-crypto). The legacy volume is kept in the top-level volumes:
    block as rollback baseline; not removed. AAATS_RISK_STATE_DIR env var
    interpolates by SYSTEM__TRADING_MODE.
  - On approval, box deploy sequence:
      1. SCP deployment/docker-compose.yml + risk/engine.py +
         scripts/migrate_state_to_per_mode.sh to box (atomic .tmp + mv -f).
      2. docker stop aaats-paper-crypto (stops the writer of the legacy
         state file; the source volume becomes idle).
      3. cd /home/aaats/aaats && bash scripts/migrate_state_to_per_mode.sh
         (idempotent: source untouched; copies into state-crypto-paper;
         renames risk_engine_state.json -> risk_engine_state.paper.json).
      4. cd /home/aaats/aaats/deployment && docker compose up -d --build
         --no-deps aaats-paper-crypto.
      5. Verify post-deploy log line: "Risk engine peak loaded from
         /app/data/state-paper/risk_engine_state.paper.json: $131.32".
         If the peak resets to $110 (LOCKED_STARTING_EQUITY), the migration
         did NOT take effect — rollback by editing docker-compose.yml to
         re-mount state-crypto and `docker compose up` again.
  - Exit: aaats-paper-crypto running on the per-mode volume layout, paper
    peak preserved, state-crypto-live volume CREATED but empty (waiting
    for first live-mode container).

[2] D.4 daily digest IMPLEMENTATION:
  - New module monitoring/daily_digest.py: build_digest(data_dir, as_of) -> str
    + build_and_send_digest() per the design memo. Pure function for the
    build, IO shell for the send.
  - New writer: data/digest_log.json — appended one line per send,
    written atomically with .tmp + replace.
  - New SQLite table cycle_log(timestamp, cycle, market) in
    /app/data/paper_trades.db, written from trading/live_paper_runner.py
    next to the heartbeat write (line ~1908). Idempotent CREATE TABLE
    IF NOT EXISTS.
  - health/watchdog.py::main loop: time-of-day check at 09:00 IST, dispatch
    build_and_send_digest() with a _digest_sent_today() guard.
  - Tests at tests/test_daily_digest.py: golden-output (fixed fixture
    state files in tmp_path, assert exact output string modulo timestamps),
    missing-state tolerance (missing files don't crash; section shows N/A),
    Action-needed trigger matrix (each trigger lights the action line).
  - Dry-run protocol per the design memo §"Dry-run plan".
  - Deploy: SCP the new files + rebuild aaats-watchdog (one new dep:
    the digest module needs the same pythonpath the watchdog has).
  - Exit: 09:00 IST tomorrow, operator receives the first digest on
    Telegram with all sections populated. The "Action needed: NONE" line
    should appear if no thresholds breached.

[3] B.2 evaluation (run ONLY if today >= 2026-05-29):
  - Run the SQL queries in docs/known_issues/2026-05-23_strategy_c3_post_b2.md
    §"Measurement protocol".
  - Compare against P1/P2/P3 pass criteria and F1/F2/F3 fail criteria.
  - Pass: close the memo as "patch verified, C3 monitored 30d".
  - Inconclusive (-$1 to -$5 range): build scripts/backtest_c3_param_sweep.py
    per the memo's fallback section. Defer the verdict until backtest
    completes.
  - Fail: re-triage C3 as HALT or REPLACE. Commit a new entry in the B.1
    triage table in 2026-05-22_live_flip_rebuild_plan.md.

[4] D.5 30-day soak day-1:
  - Defined start: the first daily digest fires with Action needed: NONE.
  - On day-1: create data/digests/ directory; archive each digest's
    full payload there per the Track C.6 requirement.
  - Operator does not need to read each digest; the test is "Action
    needed: NONE" for 30 consecutive days. Watchdog's self-heartbeat is
    the secondary signal — if the digest ever stops firing, the watchdog
    is also likely stalled.

Constraints (unchanged from sessions 1+2+3+4):
  - No SCP deploy from dirty tree.
  - `git pull --rebase` BEFORE every push. Auto-cron on box pushes
    runtime/+data/+logs/ snapshots every 15 min.
  - Push to GitHub at end of session. Session 4's push may have been
    delayed by intermittent operator GitHub connectivity — verify the
    branch is up to date with origin at session 5 start.
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Keep paper-crypto running. Use `--no-deps aaats-paper-crypto` for
    rebuilds (except the watchdog which has no siblings).
  - ASCII-only in any deploy script that runs on the Windows operator
    workstation (cp1252 codec failure; surfaced session 4).
  - aaats-watchdog is now in production. The compose entry uses the rw
    data mount and CYCLE_INTERVAL_SEC=900 (15-min stale threshold = 45min).
    Do NOT lower the threshold without operator approval (would runaway-
    restart paper-crypto).

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md
    ([0]+[1]+[2] ship reports).
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md
    ([2] D.4 implementation, [4] D.5 begin).
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with session 6 prompt.
  - Commit + push.
  - Ping operator on: A.1 compose-change review ([1]), C3 re-triage if
    B.2 fails ([3]), or kill-switch events (drawdown more negative than
    -30%, share-equality delta > $0.50, container failing to start).
    Otherwise no ping needed.

Start with [0]: it's the lowest-risk highest-leverage item (one line of
code, one line of config, one new test, one deploy). [0] unblocks
"halt_on_critical=True" which is the doctrine-correct default for the
kill switch. While [0]'s SCP cycle is in-flight, prep the operator
question for [1]. Then [2] is the rest of the session.

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents may hit
Write-tool permission denials. If you delegate, instruct subagents to
return content in their reply, not call Write directly.
```
