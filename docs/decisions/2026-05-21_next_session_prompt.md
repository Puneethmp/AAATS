# Next Claude Code session prompt (session 9)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-23 (post session 8 — operator-halt MTM gap CLOSED via entry/exit gate split; box deploy still pending this session per session-8 close; D.6 lint dropped silent-except 77 → 71; alerts-log smoke validated end-to-end; B.2 still ineligible until 2026-05-29; D.5 day-1 still parked at -33.4% drawdown).

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, session 9. Session 8 shipped:

  [0] OPERATOR-HALT MTM GAP CLOSED. Adopted option (a) from the session-8
      prompt: split the per-emission kill gate into ENTRY and EXIT variants
      so the operator halt blocks new entries without freezing open
      positions. Layout in trading/live_paper_runner.py:
        - New private helper _mark_to_market_and_decide() drives engine
          update_portfolio + update_market once per emission and returns
          the more severe of the two decisions. Latent bug fixed along
          the way: pre-session-8 the helper only returned update_market's
          decision, so a fresh engine that hit HALT_ALL via
          update_portfolio still returned ALLOW because the market peak
          was freshly seeded.
        - apply_kill_switch_gate (ENTRY) now consults
          foundation.kill_switch.is_halted(market) BEFORE the engine
          decision. Blocks BUY emission on operator halt + HALT_ALL +
          HALT_MARKET.
        - apply_kill_switch_exit_gate (EXIT, NEW) only blocks on
          catastrophic HALT_ALL. HALT_MARKET and operator halt allow the
          SELL through so positions can bleed via ATR / per-trade /
          converge.
        - execute() routes BUY through entry gate, SELL through exit
          gate.
        - run_crypto + run_india no longer short-circuit on is_halted —
          they log the halt once and proceed.
        - C3 (altcoin_reversion.py) and C6 (bollinger_range.py) import
          the new _exit_gate_check alias and use it on SELL paths. C1
          (stat_arb.py) _run_pair accepts a new exit_gate_check kwarg.
      Coverage: 12 new tests at tests/test_operator_halt_mtm_gap.py +
      1 updated tests/test_kill_trigger_paths.py test.
      Box state at session-8 close: workstation-shipped, NOT yet box-
      deployed (deploy script + paramiko run is session-9 item [0]).

  [0a] OPEN-POSITION VERIFICATION (done): zero open positions on box.
      -33.4% is realized loss. [0c] forced-MTM NOT needed.

  [3] ALERTS-LOG SMOKE CONFIRMED. Synthetic send_alert inside
      aaats-paper-crypto created data/alerts_log.json (188 bytes, one
      row). Lazy creation contract holds.

  [2] D.6 LINT CHIP-AWAY. silent-except 77 → 71 (-6 hits):
      execution/paper_trader.py 94/106/111 (sqlite OperationalError),
      execution/status_db.py:50 (sqlite OperationalError, added logger),
      foundation/mode_manager.py:128 (LIVE-activation alert),
      diagnostics/d2_ml_dist.py:116 (per-bar score_signal). Baseline
      ratcheted at tools/lint/silent_except_baseline.txt.
      loguru-printf unchanged at 181.

  [2b] LOGURU-ONLY SCOPING — deferred again. Chip-away still progresses
      fine without rule narrowing.

  [4] D.5 DAY-1 — still parked (crypto operator-halted, action != NONE).

Box state at session-8 close:
  - Operator halt still set: data/halt_state.json says
    {us:true, india:true, crypto:true} (unchanged since 2026-05-22 15:41 UTC).
  - Container image: paper-crypto sha256:4905e304… (session-7 deploy);
    metrics sha256:25f222ac…; watchdog sha256:d0ad9ab1…. The session-8
    code changes are workstation-only until [0] of this session deploys.
  - State file anomaly: /app/data/risk_engine_state.paper.json,
    portfolio_state.paper.json, equity_curve.json were MISSING when
    queried at session-8 [0a] verification. data/state/risk_engine_state.json
    does exist per session-7 doctrine. Worth a session-9 read to confirm
    whether the persistence path moved or the files are truly absent.

Status logs at docs/decisions/2026-05-22_live_flip_rebuild_plan.md
"2026-05-23 (session 8)" and docs/decisions/2026-05-21_track_d_reliability_addendum.md
"2026-05-23 (session 8)" have full ship reports.

Goal of this session: ship the session-8 code to the box, decide whether
to clear or hold the operator halt, and chip more lint. Execute in order:

  [0] SESSION-8 BOX DEPLOY (~30-45 min). Build a paramiko SCP script
      modeled on scripts/deploy_session7_kill_alerts_lint.py. Files to
      roll:
        - trading/live_paper_runner.py (gate split + run_crypto/run_india
          short-circuit removal)
        - trading/altcoin_reversion.py (C3 _exit_gate_check)
        - trading/bollinger_range.py (C6 _exit_gate_check)
        - trading/stat_arb.py (C1 exit_gate_check propagation)
        - execution/paper_trader.py (lint)
        - execution/status_db.py (lint + new logger)
        - foundation/mode_manager.py (lint)
        - diagnostics/d2_ml_dist.py (lint)
        - tools/lint/silent_except_baseline.txt (ratchet)
      Rebuild aaats-paper-crypto only (--no-deps); metrics + watchdog
      images unchanged. Capture rollback at
      .rollback/2026-05-XX_session8_operator_halt_gap/MANIFEST.txt with
      pre/post SHAs. Smoke gates:
        (a) docker logs aaats-paper-crypto --since 60s should show
            "Crypto market under OPERATOR HALT — new entries blocked;
            open positions continue to MTM" (the new wording),
        (b) docker exec aaats-paper-crypto python -c
            "from trading.live_paper_runner import apply_kill_switch_exit_gate;
             print(apply_kill_switch_exit_gate)" returns the function
            (proves the new symbol shipped),
        (c) digest dry-run still renders.

  [0b] STATE FILE INVESTIGATION (read-only, ~5 min after [0]). Inside
      aaats-paper-crypto:
        docker exec aaats-paper-crypto python -c "
        import os, json
        for p in ['/app/data/risk_engine_state.paper.json',
                 '/app/data/portfolio_state.paper.json',
                 '/app/data/equity_curve.json',
                 '/app/data/state/risk_engine_state.json',
                 '/app/data/state/risk_engine_state.paper.json']:
            exists = os.path.exists(p)
            size = os.path.getsize(p) if exists else 0
            print(f'{p}: exists={exists} size={size}')
        "
      Branch logic:
        - If state/risk_engine_state.paper.json (with .paper. suffix)
          exists: per-mode isolation IS active; the unsuffixed files
          are legacy and can be ignored. Note in session-9 status log.
        - If only state/risk_engine_state.json (no suffix) exists:
          per-mode isolation is NOT active. Filed as a session-10
          item; don't block on it.

  [1] OPERATOR HALT — REVIEW WITH OPERATOR.
      Current state: data/halt_state.json {us:true, india:true, crypto:true}
      since 2026-05-22 15:41 UTC. Engine still computes -33.4% drawdown.
      Post-deploy the runner will continue to honor the halt (entries
      blocked), but if the engine peak/current persist past this session,
      the engine-level HALT_MARKET also stays active.
      Operator question to surface: "want to clear the operator channel
      now that MTM/exit logic is unblocked? If yes, run
      `python kill.py --reset crypto` on the box. Engine kill remains
      until paper-crypto recovers >-15%." Don't reset autonomously — ping
      the operator first.

  [2] B.2 EVALUATION (only if today >= 2026-05-29). Same protocol as
      session-8 prompt's [1]. If today < 2026-05-29, SKIP to [3]/[4]/[5].

  [3] D.6 LINT CHIP-AWAY (~1-2 hours). Strong candidates after session 8:
        - monitoring/metrics_exporter.py lines 199/212/220 — silent
          `except Exception: pass` (the only inline `pass` style remaining
          in the silent-except output). May be doctrine-correct (exporter
          must never raise into Prometheus); confirm with the file's
          docstring before chipping.
        - markets/india/token_manager.py:136 (silent-except).
        - markets/crypto/universe.py:226 (silent-except, narrow except).
        - health/watchdog.py:183 (silent OSError).
      For each: investigate, then either add log.debug body or annotate
      `# noqa: silent-except` with a one-line "why doctrine-correct"
      comment. Ratchet baseline downward.

  [4] D.5 DAY-1 PASSIVE CHECK. If today's first digest fires
      "Action needed: NONE", note in the status log that day-1 has begun.
      Otherwise skip.

  [5] STATE-PERSISTENCE FOLLOWUP (only if [0b] showed missing files).
      If session-8 [0a]'s missing-files surprise persists, file a
      docs/known_issues/2026-05-XX_state_file_anomaly.md memo with the
      [0b] query output. Don't fix in-session; treat as a triage.

Constraints (unchanged from sessions 1-8):
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
  - Pre-existing test failures NOT regressions: tests/test_dual_ledger_drift.py
    ::test_dual_ledger_drift_bounded[runtime] (runtime/ box-cron drift),
    tests/test_decision/test_consensus_voting.py::test_high_uncertainty,
    tests/test_ml/test_xgboost_ensemble.py (4 boundary cases),
    tests/test_india/test_angel_one_integration.py (credential errors).
    Don't try to fix unless that's your assigned scope.

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md.
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md.
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with the
    session 10 prompt.
  - Commit + push.
  - Ping operator on: kill-switch reset decision (item [1] above),
    deploy smoke failure, container failing to start, share-equality delta
    > $0.50, drawdown more negative than -35%. Otherwise no ping needed.

Start with [0] box deploy (~30-45 min), then [0b] state file investigation
(5 min), then [1] operator halt review (ping required), then [3] lint
chip-away while waiting for operator. The deploy is the highest-leverage
work — without it, the session-8 fix is workstation-only and the box
continues to short-circuit on operator halt. Estimate: 60-90 min for
[0]+[0b]+[1], then [3] backfills the rest of the session.

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents may hit
Write-tool permission denials. If you delegate, instruct subagents to
return content in their reply, not call Write directly.
```
