# Next Claude Code session prompt (session 12 — operator-return review)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session on return from the away period. Session 10+11 (consolidated) shipped Phase 1 and Phase 2 autonomously on 2026-05-23 (PASS); the D.5 30-day soak is live on the $200 paper-crypto book with the C3 divergence-watcher armed for days 1-7.

**Updated:** 2026-05-23 post session 10+11 success. D.5 day-1 fired at 2026-05-23T12:46:32Z. Divergence-watcher day-7 deactivation: 2026-05-30T12:46:32Z. D.5 soak day-30 ETA: 2026-06-22T12:46:32Z.

---

## Paste this block into the next Claude Code session

```
Context: AAATS operator-return review. The bot has been running the
D.5 30-day soak since 2026-05-23T12:46:32Z autonomously. This session
processes the away-period queue, decides whether C.6 (D.5 30-day no-
intervention soak) and C.7 (B.3 4-week profitability) gates passed,
and stages the next move (live flip prep, or restart-day-1 if the
soak was interrupted).

Session 10+11 shipped (REFERENCE — do not redo):

  [P1.0] PF5.6 D.1 auto-halt isolation tests (4 pass).
  [P1.1] PF5.5 100bps slippage stress tests (2 pass).
  [P1.2] scripts/reset_paper_book_200.py + 7 tests.
  [P1.3] monitoring/daily_digest.py C3 divergence-watcher + 6 tests.
  [P1.4] docs/runbooks/2026-05-23_operator_away_protocol.md updated
         (D2 override + D3 watcher row in decision matrix).
  [P1.5] docs/conventions/deploy_discipline.md import-graph guard note.
  [P1.6] scripts/deploy_session10_watcher.py shipped to box —
         paper-crypto rebuilt sha256:1a06f1a3de03 -> sha256:ddbba66310e3,
         watchdog rebuilt -> sha256:653fbdb892f4. Smoke A/A'/B/C green.
         Rollback: .rollback/2026-05-24_session10_watcher_deploy/.
  [P2.0] D.5 reset SUCCESS at 2026-05-23T12:46:32Z. 4 attempts total;
         3 fixes applied along the way (watchdog stop, rm -f containers,
         india seed, state archive). All persistent code on origin/main.
  [P2.1] D.5 day-1 marker verified: $200 seed, watcher armed days 1-7,
         [-$2,+$2] band on C3 P&L.
  [P2.2] PF5.7 container-kill smoke green (live box).
  [P2.3] PF5.8 flash-crash -21% drawdown -> engine HALT_ALL fires,
         operator channel uncrossed, new entries blocked, reset clears.
  [P2.4] Telegram pager validated end-to-end (message_id=2830,
         HTTP 200 from sendMessage API).
  [P2.5] Watcher armed confirmation: day 0/7, pnl=$0.00, no breach.
  [P2.7] Operator-bye sent (cid c75c134e-67b3-4c97-adf5-767b4d28c706).

================================================================
PHASE A — Pager + digest queue review (DO FIRST, ~30-60 min)
================================================================

  [A.1] Read every Telegram pager queued since 2026-05-23T13:00Z.
        Source-of-truth: data/alerts_log.json on box (severity=critical
        rows + [PAGER] prefix). Cross-reference Telegram chat 1946109268
        if accessible. Tabulate:
          - timestamp
          - subsystem (which alert source)
          - what auto-action the pre-auth matrix took
          - whether operator intervention is now needed.

  [A.2] Read every daily digest from data/digests/ archive
        (alternative: data/digest_log.json index). Look for:
          - `Action needed != NONE` streaks (3+ in a row = was paged).
          - The C3 P&L since day-1 row in days 1-7 — did it stay within
            [-$2, +$2]? If exited, the watcher should have halted C3
            and that should appear in [A.1].
          - Strategy halt entries (any auto-halts during the period).

  [A.3] Read data/alerts_log.json full timeline. Tabulate by severity
        (info / warn / critical). Note resolution rate — high open-alert
        backlog == operator triage needed.

  [A.4] Check soak counter. D.5 success = 30 consecutive NONE-NONE
        digests starting 2026-05-23. If interrupted (any reset or
        non-NONE digest streak ended), the day-1 counter restarted —
        check the latest d5_day1_marker.json on box for the current
        counter origin.

  Output of Phase A: a one-page operator briefing with:
    - Pager count + last-action-taken table
    - Soak status (day N of 30 / interrupted at day N / completed)
    - Strategy halts that need operator decision (resume vs keep halted)
    - Any pager unaddressed by pre-auth matrix (needs decision)

================================================================
PHASE B — Soak verdict + B.2/B.3 evaluation
================================================================

  [B.1] D.5 verdict (C.6 gate):
          - If 30 consecutive NONE-NONE digests reached → C.6 PASS.
          - If interrupted → C.6 NOT YET; decide whether to restart
            day-1 or escalate (e.g. if interruption was a real bug).

  [B.2] B.2 evaluation (if 2026-05-29 was reached during the away
        period). Per docs/known_issues/2026-05-23_strategy_c3_post_b2.md:
          - Read the auto-evaluation result file (TBD path; per the
            decision protocol).
          - If P1/P2/P3 all green → C3 stays active; proceed to B.3.
          - If any F1/F2/F3 fired → C3 should already be halted; verify
            and document the halt reason.

  [B.3] B.3 4-week soak check (if it started during away). Compare
        final equity vs starting $200:
          - >= $200 → C.7 PASS.
          - <  $200 → C.7 FAIL → re-triage per C.7's failure-branch logic
            (see docs/decisions/2026-05-22_live_flip_rebuild_plan.md).

  [B.4] If C.6 + C.7 BOTH PASS: stage Track C live-flip preparation.
        Operator-on-station decision required (per autonomy contract,
        live-flip is reserved for operator).
        If either FAILS or NOT YET: stay in paper; produce a NO-FLIP-YET
        briefing with the failed gate's specific evidence.

================================================================
PHASE C — Tree maintenance + commit
================================================================

  [C.1] Resolve any pager-driven decisions:
          - Strategies the operator wants resumed → reset_strategy() +
            commit the audit.
          - Strategies the operator wants kept halted → leave halted +
            document why in docs/known_issues/.
          - Doctrine-level decisions surfaced by pager → write a new
            docs/decisions/ doc + Cowork plan.

  [C.2] Update Status logs:
          - docs/decisions/2026-05-22_live_flip_rebuild_plan.md Status
            log (C.6/C.7/Track C outcomes).
          - docs/decisions/2026-05-21_track_d_reliability_addendum.md
            Status log (D.5 final outcome).

  [C.3] Overwrite this file (docs/decisions/2026-05-21_next_session_prompt.md)
        with the session-13 prompt. If C.6+C.7 pass and operator decides
        live-flip → session-13 is "Track C gate execution + first live
        tranche". Else → session-13 is "soak day-N continuation +
        whatever PHASE B surfaced".

  [C.4] Commit atomic per scope (Cowork chats, decision docs, status
        logs, any code fixes from pager triage). git pull --rebase
        before push.

================================================================
CONSTRAINTS (unchanged from sessions 1-11):
================================================================

  - No SCP deploy from dirty tree.
  - git pull --rebase BEFORE every push.
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Use --no-deps for rebuilds.
  - Pre-existing test failures NOT regressions: test_dual_ledger_drift_bounded[runtime],
    test_high_uncertainty, test_xgboost_ensemble (4 cases),
    test_angel_one_integration.
  - Live-flip is operator-only (per autonomy contract). C.1-C.7 gates
    must pass first. Never flip from this session autonomously.
```

---

## Status log

- **2026-05-23 (sessions 10+11 consolidated):** Phase 1 + auto-confirm + Phase 2 shipped autonomously per pre-auth. 19 new unit tests green, 4 box-smoke tests green (PF5.5/5.6 in unit suite, PF5.7/5.8 against live box), divergence-watcher live in monitoring/daily_digest.py, reset_paper_book_200.py executed successfully on 4th attempt (3 fixes layered in), D.5 day-1 marker written, operator-bye sent. Final commits: `c0a22ff` (Phase 1), `0d30c75` (P1.6 MANIFEST), `02cc4e9` `a2ddf15` `ec98d9b` `74d7d8c` (reset script fixes), `1eaaf41` (Phase 2 PF5.7/5.8 tests). All pushed to origin/main.

- **2026-05-23 D.5 day-1 fired at 2026-05-23T12:46:32Z.** Watcher window: 2026-05-23 → 2026-05-30. D.5 soak day-30 ETA: 2026-06-22.
