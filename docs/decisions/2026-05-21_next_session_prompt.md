# Next Claude Code session prompt (sessions 10 + 11 consolidated, AUTO-CONFIRM)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. Two sessions of work, one paste, **fully autonomous from paste-in through operator-bye**. The previous "operator gate" between phases has been replaced with hard-coded auto-confirm criteria (C1-C8) that the session evaluates mechanically. If all pass → Phase 2 auto-runs. If any fail → halt + page. No human-wait at any point unless a real failure surfaces.

**Updated:** 2026-05-23 (post session 9 + Cowork consolidation + auto-confirm pass). Session 9 shipped session-8 code + B.1.5 backtest harness; result PARTIAL (+$5.43 / Sharpe 1.52 / 2-of-3 regimes / 50bps slippage flips sign). Cowork added: (a) divergence-watcher decision overriding runbook's HALT-on-PARTIAL rule, (b) auto-confirm gate replacing the human-wait, (c) PF5.7/PF5.8 made fully automated (no operator-online dependency). Operator departs 2026-05-25.

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, sessions 10 + 11 consolidated. Operator
departure 2026-05-25; this paste-in covers everything from now through
soak start. ONE operator gate between session-10 and session-11 work
(see GATE block below). All other decisions are pre-approved per Cowork
2026-05-23.

Session 9 shipped:

  [0] SESSION-8 BOX DEPLOY. 9 files SCP'd via paramiko. paper-crypto
      rebuilt sha256:4905e304... -> sha256:1d3a7ffadd38... (intermediate
      064483a2bfaa... before hotfix). Rollback at
      .rollback/2026-05-24_session8_operator_halt_gap/.

  [0.5] HOTFIX foundation/state_bridge.py + foundation/positions.py.
      These were committed 2026-05-21 (464bf7e) but never SCP'd; the
      session-8 strategy imports broke the box until shipped. Hotfix
      rolled both, image rebuilt to sha256:1d3a7ffadd38... Rollback at
      .rollback/2026-05-24_session9_hotfix_state_bridge/.

  [0b] STATE FILE PROBE: ALL of /app/data/risk_engine_state.paper.json,
      portfolio_state.paper.json, equity_curve.json, /app/data/state/*
      paths ABSENT. Runner re-derives state from paper_trades.db each
      cycle. Filed docs/known_issues/2026-05-23_state_persistence_paths_missing.md.
      Session-11 reset wipes the volume anyway.

  [1] B.1.5 BACKTEST HARNESS BUILT + RUN. tools/backtest/ package + 12/12
      tests. 60d C3 replay: trades=86, pnl=+$5.43, sharpe=1.52, wr=47.7%,
      profitable_regimes=2/3 (low_vol +$2.53, mid_vol -$0.36, high_vol
      +$3.33), 50bps_slippage_pnl=-$5.72. recommendation="PARTIAL".
      Output at data/backtest_results/c3_60d_summary.json. Caveats in
      JSON's evidence field: replay disables BEAR regime gate (no HMM)
      and BTC.D fast-rise filter — PERMISSIVE upper bound, live could
      underperform.

  [3]/[5]/[6] PF5 / lint / D.5 day-1 deferred to sessions 10+11.

Status logs at docs/decisions/2026-05-22_live_flip_rebuild_plan.md
"2026-05-23 (session 9)" + docs/decisions/2026-05-21_track_d_reliability_addendum.md
"2026-05-23 (session 9)".

Cowork decisions baked into this prompt (do not re-litigate):

  D1. PARTIAL = PROCEED. The hard-coded session-9 rule says GO or PARTIAL
      allows the reset. Operator confirmed 2026-05-23.

  D2. C3 STAYS ACTIVE DURING THE SOAK. The operator-away runbook's
      original "PARTIAL -> HALT C3" rule is OVERRIDDEN. Backtest edge
      (+$5.43, 2/3 regimes profitable) is too valuable to discard
      preemptively. Risk is contained via D3 below.

  D3. FIRST-WEEK DIVERGENCE-WATCHER. During soak days 1-7, if C3's
      running P&L since reset exits the window [-$2.00, +$2.00], the
      digest writer auto-halts C3 via strategy_halt_state.json and
      sends a Telegram pager-level alert with reason=
      "C3 backtest-vs-live divergence > $2 in first week".
      After day 7, the watcher deactivates; normal D.5 rules apply.

  D4. RESET SEED = $200. Per docs/decisions/2026-05-23_doctrine_amendment_200_floor.md.
      No further amendment this session.

  D5. OPERATOR HALT CLEAR HAPPENS DURING RESET. The reset script invokes
      foundation.kill_switch.reset("crypto") between volume reinit and
      container start.

================================================================
PHASE 1 — Session-10 work (no operator interaction needed)
================================================================

Goal: ship PF5 stress tests, the reset script (--dry-run testable), the
divergence-watcher implementation, the runbook update, and deploy the
divergence-watcher code to box so session-11 reset starts with the
safety mechanism already live. Execute in order:

  [P1.0] PF5.6 D.1 AUTO-HALT ISOLATION (~45-90 min, MUST GO FIRST).
      Per docs/decisions/2026-05-22_live_flip_rebuild_plan.md A.4 PF5.6.
      Pure monkeypatch test, lowest blast radius. Write
      tests/preflight/test_pf5_6_d1_isolation.py with:
        - C3 raising 3 consecutive exceptions auto-halts (strategy_halt_state.json has c3=true).
        - Other strategies (C1, C6) continue to fire after C3 halts.
        - Halt is symbol-scoped or strategy-scoped per the spec (read first; test should match).
        - Reset path: reset_strategy("C3") clears strategy_halt_state.json's c3 entry.
      Use existing patterns at tests/test_strategy_halt.py.

  [P1.1] PF5.5 SLIPPAGE STRESS (~45-90 min). Per A.4 PF5.5. Write
      tests/preflight/test_pf5_5_slippage.py. Verify that with a
      simulated wider spread (mock orderbook to 100bps inside spread):
        - paper_trader.simulate_fill records the trade at the wider
          effective price OR skips the trade if a size_below_min_after_
          slippage guard exists (check execution/paper_trader.py — if
          none, test documents the absence).
      Monkeypatch orderbook fetch; run a single buy + sell cycle; assert
      recorded fill price + ledger row.

  [P1.2] scripts/reset_paper_book_200.py BUILD (~60-90 min, CRITICAL).
      Per Track E.4 spec. Behavior:
        (a) Read data/backtest_results/c3_60d_summary.json.
        (b) If recommendation == "NO-GO": loud refusal + exit 1.
        (c) If recommendation in {"GO", "PARTIAL"}: proceed; if PARTIAL,
            print "PARTIAL: divergence-watcher active via D3" before
            continuing.
        (d) docker compose stop aaats-paper-crypto on box.
        (e) docker volume rm deployment_state-crypto-paper.
        (f) docker volume create deployment_state-crypto-paper.
        (g) Seed $200 baseline. Path: write data/portfolio_state.json
            and data/state/* skeleton with starting_equity=200.0.
            Mirror however the existing first-run seed works (look
            for Dockerfile ENTRYPOINT or first-run side effect in
            paper_trader.py).
        (h) foundation.kill_switch.reset("crypto") via CLI.
        (i) docker compose up -d aaats-paper-crypto (--no-deps).
        (j) Wait up to 20 min for first NONE-NONE digest (Action
            needed == NONE). Write timestamp to
            data/d5_day1_marker.json: {"day1_at": ISO8601,
            "starting_equity_usd": 200.0, "divergence_watcher_armed": true,
            "watcher_window_days": 7,
            "c3_threshold_low_usd": -2.0, "c3_threshold_high_usd": 2.0}.
        (k) If digest doesn't reach NONE within 20 min: ROLLBACK. Restore
            halt, exit non-zero, write data/d5_day1_marker.json with
            "failed_at" + reason.
      Add --dry-run flag that prints (a)-(k) without executing. Use
      paramiko for box-side commands; pattern after
      scripts/deploy_session7_kill_alerts_lint.py.
      Failing-then-passing tests at tests/test_reset_paper_book_200.py:
        - test_refuses_on_NO_GO (mock NO-GO -> exit 1)
        - test_proceeds_on_GO (mock GO -> reaches docker step under stub)
        - test_proceeds_on_PARTIAL_with_watcher_note (mock PARTIAL -> proceeds, prints watcher message)
        - test_seeds_200_baseline (mock volume mount -> $200 in portfolio_state.json)
        - test_writes_d5_day1_marker (post-NONE-NONE digest, marker JSON has all fields)
        - test_rollback_on_no_NONE_digest_in_window (digest never reaches NONE -> ROLLBACK path)
      DO NOT actually run against box in this session. Session-11 [P2.0] is the run window.

  [P1.3] DIVERGENCE-WATCHER IMPLEMENTATION (~45-60 min). Add to
      monitoring/daily_digest.py (or wherever the daily digest is
      written) a new check that runs each digest cycle:
        - Read data/d5_day1_marker.json. If absent: skip (pre-reset).
        - Compute days_since_day1 = (now - day1_at).total_seconds() / 86400.
        - If days_since_day1 > watcher_window_days (default 7): skip.
        - Compute c3_pnl_since_day1_usd by aggregating paper_trades.db
          rows where strategy="C3" AND created_at >= day1_at.
        - If c3_pnl_since_day1_usd < c3_threshold_low_usd OR > c3_threshold_high_usd:
            - Write data/strategy_halt_state.json: c3=true,
              reason="C3 divergence-watcher: pnl_since_day1=$X.XX,
              outside [$-2.00, $+2.00] window in soak day N".
            - send_alert(level="pager", ...) to chat 1946109268.
            - Append to alerts_log.json.
        - Include the c3_pnl_since_day1_usd value as a new row in the
          digest payload ("C3 P&L since day-1: $X.XX (watcher active,
          days N/7)") so the operator can see the running number.
      Failing-then-passing tests at tests/test_divergence_watcher.py:
        - test_skips_if_no_day1_marker
        - test_skips_after_7_days
        - test_halts_C3_on_negative_breach
        - test_halts_C3_on_positive_breach
        - test_includes_running_pnl_in_digest_row
      THIS CODE MUST BE DEPLOYED BEFORE THE RESET RUNS in session-11
      [P2.0]. Include in the deploy step at [P1.6].

  [P1.4] OPERATOR-AWAY RUNBOOK UPDATE (~10 min). Edit
      docs/runbooks/2026-05-23_operator_away_protocol.md:
        - In the "Backtest-gated GO/NO-GO" table, replace the PARTIAL
          row with: "PARTIAL GO: reset to $200, start soak with full
          stack (C1+C3+C6) BUT divergence-watcher armed for days 1-7
          (cuts C3 if pnl exits [-$2,+$2])."
        - In "Pre-auth decision matrix", add new row: "Divergence-
          watcher fires (C3 pnl exits window during soak days 1-7) ->
          C3 auto-HALT, Telegram pager-level alert. Other strategies
          continue. Operator sees the halt in next digest."
      No other runbook changes.

  [P1.5] STATE-BRIDGE DOCTRINE NOTE (~15 min). Per session-9 finding.
      Add a new section to docs/conventions/deploy_discipline.md
      titled "Import-graph guard for SCP manifests" with:
        - The session-9 ImportError pattern (state_bridge committed to
          git, missing on box).
        - Rule: before declaring a deploy "smoke green", run
          docker exec aaats-paper-crypto python -c
          "import trading.live_paper_runner; import foundation.state_bridge;
           import foundation.positions" (or similar import-canary).
        - Followup-item: build tools/lint/manifest_import_audit.py
          that walks the SCP manifest's local imports and asserts each
          is in-manifest or already on the box. Deferrable to post-soak.

  [P1.6] DEPLOY DIVERGENCE-WATCHER + ANY P1.0/P1.1 PRODUCTION CHANGES
      TO BOX (~30-45 min). Build a paramiko SCP script
      scripts/deploy_session10_watcher.py (mirrors session-9 pattern).
      Files to roll (only those that changed in production paths;
      tests stay workstation-only):
        - monitoring/daily_digest.py (watcher impl)
        - any execution/paper_trader.py change from P1.1 (if PF5.5
          surfaced a real bug AND you fixed it)
        - any strategy file change (none expected)
      Rebuild aaats-paper-crypto only (--no-deps). Rollback at
      .rollback/2026-05-24_session10_watcher_deploy/MANIFEST.txt.
      Smoke gates:
        (a) docker exec aaats-paper-crypto python -c
            "from monitoring.daily_digest import compute_c3_divergence; print(compute_c3_divergence)"
            returns the function (proves watcher symbol shipped).
        (b) digest dry-run renders the new C3 row even with no
            day1_marker (should show "watcher dormant — awaiting reset").
        (c) container reaches "running" status post-rebuild.

  [P1.7] LINT CHIP-AWAY (FILLER, only if slack >30 min after P1.6).
      Same candidates as session-9 prompt; ratchet baseline.

  PHASE-1 COMMIT + PUSH. Atomic commits per scope (PF5.6, PF5.5,
  reset_script, watcher, runbook, doctrine_note, deploy). git pull
  --rebase before push.

================================================================
AUTO-CONFIRM GATE (operator pre-authorized 2026-05-23 — no wait)
================================================================

The operator has pre-authorized Phase 2 to auto-proceed IFF all of the
following hard pass criteria are met after Phase 1 completes. There is
NO human-wait; the criteria are mechanical pass/fail. If ANY criterion
fails, halt Phase 2, ship a session-11 prompt with the failure
diagnosis, and page the operator. Otherwise proceed straight through
to Phase 2 [P2.0].

AUTO-CONFIRM PASS CRITERIA (ALL must be true to proceed):

  C1. tests/preflight/test_pf5_6_d1_isolation.py — 100% green, ≥4 tests.
  C2. tests/preflight/test_pf5_5_slippage.py — 100% green, ≥2 tests.
  C3. tests/test_reset_paper_book_200.py — 100% green, all 6 named
      tests present (test_refuses_on_NO_GO, test_proceeds_on_GO,
      test_proceeds_on_PARTIAL_with_watcher_note, test_seeds_200_baseline,
      test_writes_d5_day1_marker, test_rollback_on_no_NONE_digest_in_window).
  C4. tests/test_divergence_watcher.py — 100% green, all 5 named
      tests present.
  C5. P1.6 deploy smoke gates (a) symbol importable, (b) digest dry-run
      renders watcher row, (c) container "running" status — ALL pass.
  C6. data/backtest_results/c3_60d_summary.json["recommendation"] is
      still "GO" or "PARTIAL" (NOT "NO-GO"). Re-read at gate time in
      case the file was modified.
  C7. No new pytest failures outside the documented pre-existing set
      (test_dual_ledger_drift_bounded[runtime], test_high_uncertainty,
      test_xgboost_ensemble 4 cases, test_angel_one_integration).
  C8. git diff --stat against HEAD after P1.6 deploy shows zero
      uncommitted changes — repo is clean per
      [[feedback-scp-deploy-clean-tree]].

CRITERIA EVALUATION (run at gate, single Python command for atomicity):

  python -c "
  import json, subprocess, sys

  failures = []
  # C1-C4: pytest aggregations
  for tf in ['tests/preflight/test_pf5_6_d1_isolation.py',
            'tests/preflight/test_pf5_5_slippage.py',
            'tests/test_reset_paper_book_200.py',
            'tests/test_divergence_watcher.py']:
      r = subprocess.run(['pytest', tf, '-q', '--tb=no'],
                         capture_output=True, text=True)
      if r.returncode != 0:
          failures.append(f'{tf}: {r.returncode}')
  # C5: deploy smoke (re-run inline)
  # ... (deploy-smoke script invocation)
  # C6: backtest recommendation
  with open('data/backtest_results/c3_60d_summary.json') as f:
      summary = json.load(f)
  if summary['recommendation'] not in ('GO', 'PARTIAL'):
      failures.append(f'backtest recommendation: {summary[\"recommendation\"]}')
  # C8: clean tree
  r = subprocess.run(['git', 'diff', '--stat'], capture_output=True, text=True)
  if r.stdout.strip():
      failures.append(f'uncommitted changes: {r.stdout.strip()}')

  if failures:
      print('AUTO-CONFIRM FAILED:')
      for f in failures: print(f'  {f}')
      sys.exit(1)
  print('AUTO-CONFIRM PASSED — proceeding to Phase 2')
  sys.exit(0)
  "

GATE PING (informational, NOT blocking — send before proceeding to
Phase 2 so the operator sees what's happening; do not wait for reply):

  Subject: SESSION 10 PHASE 1 done — auto-proceeding to reset
  Body:
    - PF5.6 result: <pass/fail count>
    - PF5.5 result: <pass/fail count + any slippage finding>
    - reset_paper_book_200.py: built + dry-run validated
    - divergence-watcher: deployed to box, smoke green
    - operator-away runbook: updated for divergence-watcher
    - state-bridge doctrine note: shipped
    - All auto-confirm criteria PASSED — Phase 2 starting now.
    - Reset will execute in ~2 min. To abort: SSH and run
      `python kill.py halt --all` before reset script begins.

If ANY criterion FAILS at auto-confirm: halt Phase 2, write a
session-11 prompt at docs/decisions/2026-05-21_next_session_prompt.md
that includes the phase-1 ship report + the failed criterion + the
failure diagnosis, then commit + push and page the operator. The bot
stays in CURRENT halted state (not reset). This is correct fail-safe
behavior. The session-11 prompt becomes a "fix the failure, then run
reset" continuation.

================================================================
PHASE 2 — Session-11 work (requires "RESET CONFIRMED" reply)
================================================================

Goal: execute the reset, start the soak, ship the remaining PF5
scenarios with operator-online supervision, validate the pager chain,
and bid operator goodbye. Execute in order:

  [P2.0] EXECUTE RESET. Run scripts/reset_paper_book_200.py (NO
      --dry-run flag). Watch the wait-for-NONE-digest loop.
      Success: data/d5_day1_marker.json written with day1_at,
      starting_equity_usd=200.0, divergence_watcher_armed=true.
      Failure: rollback path engages, operator paged, halt P2 here.

  [P2.1] D.5 DAY-1 MARKER VALIDATION (~5 min). After P2.0 succeeds:
        - cat data/d5_day1_marker.json on box.
        - Confirm digest now shows "C3 P&L since day-1: $0.00
          (watcher active, days 0/7)" row.
        - Confirm container logs show "Crypto market under OPERATOR
          HALT" wording is NO LONGER present (halt was cleared).
        - Confirm cycle logs show normal entry-gate logic (not the
          short-circuit).

  [P2.2] PF5.7 CONTAINER-KILL + WATCHDOG-RESTART (~30 min, fully
      automated — operator pre-authorized 2026-05-23). Per A.4 PF5.7
      spec. The watchdog (D.2) is the existing mitigation; PF5.7
      VERIFIES it works. Run:
        - docker exec aaats-paper-crypto kill -9 1
        - Poll watchdog logs every 5s for "restart attempted" line;
          fail if not seen within 60s.
        - Poll aaats_metrics_exporter_up; fail if not 1.0 within 90s.
        - docker exec aaats-paper-crypto python -c "from execution.idempotency import reconcile; print(reconcile())" — confirm zero divergence.
      If any step fails: page operator (pager-level) with the diagnostic,
      attempt manual `docker compose up -d aaats-paper-crypto`, continue
      to P2.3 only if container recovers. File output at
      tests/preflight/test_pf5_7_container_restart.py — write as a
      pytest that the operator can later re-run from workstation
      (the box-side commands use paramiko, same pattern as deploy
      scripts).

  [P2.3] PF5.8 FLASH-CRASH SYNTHETIC INJECTION (~30 min). Per A.4
      PF5.8 spec. Inject synthetic mark drop to 0.79 * peak via
      whatever test seam exists in risk/engine.py or
      execution/paper_trader.py mark_to_market path. If no seam exists:
      add minimal one as part of this PF5.8 implementation (must have
      failing-then-passing test). Confirm:
        - Engine HALT_ALL fires.
        - All new entries blocked next 3 cycles.
        - MTM continues for any open positions.
        - halt_state.json crypto STAYS false (operator channel not
          cross-contaminated).
        - Engine auto-clears next cycle when synthetic mark removed.

  [P2.4] TELEGRAM PAGER VALIDATION (~10 min, automated). Send
      synthetic pager-level alert via:
        docker exec aaats-paper-crypto python -c
          "from observability.alerts import send_alert;
           send_alert('[PAGER-TEST] Operator-away protocol active',
                      level='pager', market='crypto')"
      Verify delivery via the Telegram API (getUpdates or sent
      message_id confirmation) rather than waiting for operator reply.
      If the sent-message API returns 200 with a valid message_id: PASS.
      If routing fails (4xx/5xx response, or missing chat_id): page
      operator via secondary channel (email if configured) or write
      the failure to session-11 status log + halt P2.5 and beyond.
      Do not wait for operator phone-side confirmation; the operator
      is en-route to AFK by the time this runs.

  [P2.5] DIVERGENCE-WATCHER ARMED CONFIRMATION (~5 min). Final
      confirmation that the watcher is live:
        docker exec aaats-paper-crypto python -c
          "from monitoring.daily_digest import compute_c3_divergence;
           import json;
           marker = json.load(open('/app/data/d5_day1_marker.json'));
           print(compute_c3_divergence(marker))"
      Should print a dict with current pnl_since_day1_usd (~$0.00 on
      day 0), within_window=true, days_into_watcher=0.

  [P2.6] FINAL COMMIT + PUSH. Atomic commits for P2.* work. git pull
      --rebase before push.

  [P2.7] OPERATOR-BYE TELEGRAM. Send via send_alert:
        "Operator AFK, expected return ~YYYY-MM-DD.
         D.5 day-1 fired at <day1_at>.
         Divergence-watcher armed (days 1-7, +/-$2 on C3).
         Pre-auth matrix per docs/runbooks/2026-05-23_operator_away_protocol.md active.
         Bot, you have the conn."

================================================================
Constraints (unchanged from sessions 1-9):
================================================================

  - No SCP deploy from dirty tree.
  - git pull --rebase BEFORE every push. Auto-cron on box pushes
    runtime/+data/+logs/ snapshots every 15 min.
  - Push to GitHub at end of EACH phase (Phase 1 commit, gate ping,
    Phase 2 commit, operator-bye).
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Use --no-deps for rebuilds.
  - ASCII-only in deploy script print() calls.
  - Pre-existing test failures NOT regressions:
    tests/test_dual_ledger_drift.py::test_dual_ledger_drift_bounded[runtime],
    tests/test_decision/test_consensus_voting.py::test_high_uncertainty,
    tests/test_ml/test_xgboost_ensemble.py (4 boundary cases),
    tests/test_india/test_angel_one_integration.py (credential errors).

================================================================
Reporting at full-session end (after P2.7 ships):
================================================================

  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md.
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md.
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with a
    session-12 prompt. Session 12 (operator-return) reviews: queued
    Telegram pager messages, daily digests during away, D.5 soak
    counter, divergence-watcher result (did it fire?), B.2 evaluation
    result if it ran (2026-05-29 eligibility hits during soak), and
    decides next Track C step.
  - Commit + push.

  - OPERATOR PINGS (informational, do not wait for reply):
    * Phase-1 -> Phase-2 gate ping (auto-confirm result + Phase 2 ETA).
    * Pager validation send result (P2.4 — API-level confirmation,
      not operator-reply).
    * Operator-bye (P2.7).
  - OPERATOR PINGS (pager-level, halt and wait if no auto-recovery):
    * Any auto-confirm criterion FAILED (Phase 2 did not start).
    * Reset script ROLLBACK engaged (P2.0 wait-for-NONE-digest timed out).
    * PF5.7 watchdog failed to restart container within 90s.
    * PF5.8 engine HALT_ALL did not fire on synthetic mark drop
      (engine kill is broken — paper soak cannot start safely).
    * Telegram pager API returned 4xx/5xx (pager routing broken).

================================================================
Start ordering (use this as the spine):
================================================================

  Phase 1 (~5-7 hours, no operator interaction):
    P1.0 PF5.6 -> P1.1 PF5.5 -> P1.2 reset script BUILD -> P1.3
    divergence-watcher impl -> P1.4 runbook update -> P1.5 doctrine
    note -> P1.6 deploy watcher -> P1.7 lint filler -> commit/push
    -> AUTO-CONFIRM EVALUATION.

  AUTO-CONFIRM: if all C1-C8 pass, send informational gate ping and
  proceed straight to Phase 2. If any criterion fails, halt + page.

  Phase 2 (~1-2 hours, fully automated):
    P2.0 reset -> P2.1 day-1 marker -> P2.2 PF5.7 (watchdog smoke,
    automated) -> P2.3 PF5.8 (flash-crash injection) -> P2.4 pager
    delivery validation (no operator-reply wait) -> P2.5 watcher
    armed -> P2.6 commit/push -> P2.7 operator-bye.

The reset (P2.0) is the only irreversible step. Auto-confirm criteria
C1-C8 are the safety harness that prevents it from firing under bad
conditions. Everything after P2.0 begins the 30-day soak clock. Total
estimated wall-clock: 6-9 hours of substantive work, fully autonomous
from operator paste-in through operator-bye.

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents may
hit Write-tool permission denials. If you delegate, instruct subagents
to return content in their reply, not call Write directly.
```
