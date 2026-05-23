# Next Claude Code session prompt (session 8)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-24 (post session 7 — session-6 changes deployed to box; C1 stat_arb kill-gate wired and tested; D.6 lint chip-away dropped baseline -10/-3).

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, session 8. Session 7 shipped:

  [0] Session-6 BUNDLED BOX DEPLOY via scripts/deploy_session7_kill_alerts_lint.py.
      Rebuilt aaats-paper-crypto + aaats-metrics + aaats-watchdog (--no-deps).
      Post-deploy SHAs at .rollback/2026-05-24_session7_kill_alerts_lint/MANIFEST.txt:
        paper-crypto  sha256:4905e304…
        metrics       sha256:25f222ac…
        watchdog      sha256:d0ad9ab1…
      Smoke gates green: digest dry-run renders correct band wording
      ("Action needed: drawdown -33.4% past portfolio-kill threshold (-20%);
      all new entries blocked, open positions continue to mark-to-market"),
      Row 7 self-up gauge live on :9091/metrics (aaats_metrics_exporter_up=1.0).

      SURFACED FINDING — operator-channel halt was being silently ignored
      pre-deploy. Box data/halt_state.json was {us:true, india:true, crypto:true}
      (set 2026-05-22 17:41 UTC, ~13 hours pre-deploy). Pre-deploy run_crypto
      ignored it; post-deploy the session-6 is_halted("crypto") gate fires
      correctly and the runner short-circuits with "Crypto market HALTED
      (kill switch) — skipping cycle". OPERATOR DECISION: keep crypto halted
      (-33.4% drawdown is past portfolio-kill threshold). C1 is not trading
      this session.

      SEMANTIC GAP SURFACED (session 8 item; see [4] below): the runner-wide
      short-circuit ALSO stops MTM and exit logic for open positions. The
      engine-level kill's documented semantics are "block new entries, keep
      MTM". This is a real divergence; needs resolution.

  [2] C1 stat_arb standalone kill-gate WIRED + tested. run_stat_arb_crypto
      and _run_pair now accept full_positions / full_portfolio kwargs and
      resolve apply_kill_switch_gate once per cycle. Gate consulted at BUY
      emission (entry) AND SELL emission (CONVERGE / HARD_STOP / TIME_STOP).
      Parity with C3 (altcoin_reversion.py) and C6 (bollinger_range.py).
      Call site in trading/live_paper_runner.py:1670 passes positions+portfolio.
      Tests: tests/test_stat_arb_kill_gate.py (4/4 green).

  [3] D.6 lint chip-away. execution/paper_executor.py lines 126/144/150/217/268/276/294
      converted to f-string (Row 17 motivation). execution/idempotency.py lines
      179/191/200 silent-except handlers gain log.debug() bodies. Baseline
      ratcheted: silent-except 80 → 77, loguru-printf 188 → 181 (-13 total).
      ratchet CI gate at tests/test_lint_silent_except.py green.

  [4] D.5 day-1 STILL PARKED (drawdown -33.4%, action needed != NONE).

Status logs at docs/decisions/2026-05-22_live_flip_rebuild_plan.md
"2026-05-24 (session 7)" and docs/decisions/2026-05-21_track_d_reliability_addendum.md
"2026-05-24 (session 7)" have full ship reports.

Goal of this session: address the operator-halt MTM gap surfaced in session 7,
chip lint baseline further, and run B.2 evaluation if eligibility window has
opened. Execute in order:

  [0] OPERATOR-HALT MTM GAP RESOLUTION. The session-7 deploy revealed that
      run_crypto short-circuits BEFORE mark-to-market and exit logic on
      is_halted("crypto"). Open positions are stuck — neither marked nor
      exited. The engine-level kill's documented semantics are "block new
      entries, keep MTM" (per docs/known_issues/2026-05-23_kill_trigger_investigation.md).
      The runner-wide short-circuit is broader than that.

      DECISION the session must make:
        (a) Move the run_crypto short-circuit BELOW the MTM/exit code so
            open positions continue to bleed correctly. C3/C6 standalone
            SELL gates also need to allow exits during operator halt. This
            requires careful test coverage of the exit paths.
        (b) Accept current behavior as intentional (operator halt = full
            stop including MTM) and document it in CLAUDE.md "Kill-switch
            semantics". This is conservative but ossifies the divergence
            between the engine kill and operator kill semantics.

      RECOMMENDATION: (a) — the engine kill already gives the operator the
      desired "block new entries, keep MTM" behavior; the operator channel
      should give a SUPERSET, not a different shape. Implementation:
        - run_crypto: hoist MTM + exit checks above the is_halted check;
          only gate the new-entry / signal-generation paths.
        - C3/C6: separate the entry gate from the exit gate. Exit gate
          should only fire on engine HALT_ALL (catastrophic), not on
          per-market HALT_MARKET or operator halt.
        - Failing-then-passing test: with operator halt set, a position
          with pnl_pct >= take_profit_pct MUST close.
      If you choose (b) instead, ping the operator first — this is a
      design decision, not implementation.

  [1] B.2 EVALUATION (only if today >= 2026-05-29). Run the SQL queries in
      docs/known_issues/2026-05-23_strategy_c3_post_b2.md "Measurement
      protocol", compare against P1/P2/P3 pass / F1/F2/F3 fail criteria.
      Close or extend the memo. If inconclusive, build
      scripts/backtest_c3_param_sweep.py per the fallback section. If
      today < 2026-05-29, SKIP B.2; reorder to [2], [3], [4].

  [2] LINT CHIP-AWAY (~1-2 hours). Pick another 10-15 top-leverage hits.
      Strong candidates:
        - execution/paper_trader.py lines 94/106/111 (silent-except, sqlite
          OperationalError, mirror the idempotency.py fix from session 7).
        - execution/status_db.py line 50 (silent-except, sqlite
          OperationalError).
        - foundation/mode_manager.py line 128 (silent-except, broad
          Exception, needs investigation).
        - diagnostics/d2_ml_dist.py line 116 (silent-except).
      For each silent-except: add log.debug or log.warning with the
      exception text. For each loguru-printf in stdlib-logging modules:
      f-string conversion. Update baseline downward.

  [2b] LINT RULE REFINEMENT (optional, ~1 Haiku session). The current
       loguru-printf rule flags any log.X("...%s...", arg) call, but many
       hits are stdlib logging where %s is correct. Refine tools/lint/silent_except.py
       to detect whether the file imports loguru vs stdlib logging at the
       top, and scope the rule to loguru-only modules. This removes false-
       positive noise from the chip-away queue.

  [3] ALERTS-LOG SMOKE. Verify the session-7 deployed alerts_log writer
      actually fires on the next HALT event. As of session-7 close,
      data/alerts_log.json was still absent (lazy creation on first
      send_alert call). On the box:
        docker exec aaats-paper-crypto python -c "from observability.alerts \
          import send_alert; send_alert('TEST session 8 smoke', market='crypto')"
        cat /home/aaats/aaats/data/alerts_log.json  # should now exist + have 1 row
      Then trigger the next watchdog tick and confirm the digest's "Alerts
      fired" row changes from "N/A (alerts_log not yet populated)" to
      "1 (0 open, 1 resolved)" or similar.

  [4] D.5 DAY-1 PASSIVE CHECK. If today's first digest fires "Action needed:
      NONE", note in the status log that day-1 has begun. Otherwise skip.

Constraints (unchanged from sessions 1-7):
  - No SCP deploy from dirty tree.
  - `git pull --rebase` BEFORE every push. Auto-cron on box pushes
    runtime/+data/+logs/ snapshots every 15 min; expect 30-60 such
    commits per session.
  - Push to GitHub at end of session.
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Keep paper-crypto running. Use `--no-deps` for rebuilds.
  - ASCII-only in deploy script print() calls — strip log output to
    ASCII before printing.
  - aaats-watchdog and aaats-paper-crypto both depend on
    deployment_state-crypto-paper volume.
  - The pre-existing test failure tests/test_dual_ledger_drift.py
    ::test_dual_ledger_drift_bounded[runtime] is NOT a session-7
    regression — it tracks runtime/ ledger drift from box auto-cron
    snapshots. Document if it persists; don't try to fix unless that's
    your assigned scope.

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md.
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md.
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with the
    session 9 prompt.
  - Commit + push.
  - Ping operator on: any change to operator-halt MTM semantics (this
    is the [0] design decision), B.2 fail-condition triage, kill-switch
    events (drawdown more negative than -35%, share-equality delta
    > $0.50, container failing to start). Otherwise no ping needed.

Start with [0] operator-halt MTM gap resolution. The longer this divergence
sits, the harder it is to reverse — every exit blocked during operator halt
silently accumulates stale pnl that the engine kill was specifically designed
to keep visible. Estimate: 60-90 min for [0] + test, then [2] / [3] / [4].

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents may hit
Write-tool permission denials. If you delegate, instruct subagents to
return content in their reply, not call Write directly.
```
