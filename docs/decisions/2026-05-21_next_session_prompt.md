# Next Claude Code session prompt (session 10)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-23 (post session 9). Session 9 shipped: [0] session-8 code to box (paramiko, 9 files), [0.5] HOTFIX `foundation/state_bridge.py` + `foundation/positions.py` (never SCP'd before — strategy file updates broke the box until shipped), [0b] state-file probe (all paths absent, filed as known issue), [1] B.1.5 backtest harness BUILT + RUN; result **PARTIAL** (+$5.43 P&L, Sharpe 1.52, 47.7% WR over 60d, 2 of 3 profitable regimes; 50bps slippage demotes P&L to -$5.72 — that's the criterion failing GO). [3] PF5, [5] lint, [6] D.5 day-1 all DEFERRED to session 10/11. Session-10 critical path: finalize PF5 stress tests + build `scripts/reset_paper_book_200.py` so session 11 (Day 3 = 2026-05-25, operator departure day) can run the reset and start the soak.

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, session 10. Session 9 shipped:

  [0] SESSION-8 BOX DEPLOY (paramiko SCP). 9 files rolled:
      trading/live_paper_runner.py, trading/altcoin_reversion.py,
      trading/bollinger_range.py, trading/stat_arb.py,
      execution/paper_trader.py, execution/status_db.py,
      foundation/mode_manager.py, diagnostics/d2_ml_dist.py,
      tools/lint/silent_except_baseline.txt. Image rebuilt
      sha256:4905e304... -> sha256:064483a2bfaa... Smoke A (new
      OPERATOR HALT log wording) + B (apply_kill_switch_exit_gate
      symbol importable) + C (digest dry-run Equity non-N/A) all
      green. Smoke D (strategy module _exit_gate_check) failed and
      exposed an ImportError chain in cycle logs — root caused to
      session-9 hotfix below. Rollback at
      .rollback/2026-05-24_session8_operator_halt_gap/MANIFEST.txt.

  [0.5] HOTFIX foundation/{state_bridge,positions}.py. Both files
      were committed to the repo on 2026-05-21 (commit 464bf7e,
      "feat(trading): wire C1/C2/C3/C6 to positions API behind
      USE_UNIFIED_LEDGER flag") but were NEVER SCP'd to the box. The
      newer strategy files we shipped in [0] import state_bridge at
      module top-level, so the box hit ImportError on every crypto
      cycle. Hotfix script c:/tmp/hotfix_state_bridge.py SCP'd both
      and rebuilt aaats-paper-crypto to sha256:1d3a7ffadd38...
      Post-hotfix logs show C3 evaluating ADA/USDT and correctly
      blocking the SELL on HALT_ALL via the new exit gate (contract
      exactly as designed). Rollback at
      .rollback/2026-05-24_session9_hotfix_state_bridge/MANIFEST.txt.

  [0b] STATE FILE PROBE (read-only). ALL of /app/data/risk_engine_state.paper.json,
      portfolio_state.paper.json, equity_curve.json, /app/data/state/*
      paths are ABSENT inside aaats-paper-crypto. The /app/data/state/
      directory itself does not exist. Runner re-derives state every
      cycle from paper_trades.db (works, no persistence). Filed at
      docs/known_issues/2026-05-23_state_persistence_paths_missing.md.
      Session 11 reset wipes state-crypto-paper volume anyway, so no
      further action this session.

  [1] B.1.5 BACKTEST HARNESS BUILT AND RUN. Result: **PARTIAL.**
      Package: tools/backtest/{__init__,historical_data,c3_replay,
      run_b15_c3}.py. Reuses C3 PURE helpers (_compute_z_score,
      _rsi, _realized_daily_vol, _compute_trade_size) directly;
      reimplements the entry/exit driver to step through historical
      bars deterministically (the strategy module's run_*_crypto()
      is wall-clock + DB-coupled and not appropriate for replay).
      Output at data/backtest_results/c3_60d_summary.json:
        trades=86, pnl_usd=+$5.43, sharpe=1.52, win_rate=47.7%
        profitable_regime_count=2/3 (low_vol +$2.53, mid_vol -$0.36,
                                     high_vol +$3.33)
        slippage_sensitivity_50bps_pnl_usd=-$5.72  <- demotes from GO
        recommendation="PARTIAL"
      Tests at tests/test_b15_backtest_harness.py — 12/12 green
      (synth dip-recover -> fires profitable; synth flat -> 0 trades
      -> NO-GO; recommendation threshold table parametrized over 9
      boundary cases + harness-failed short-circuit). LIMITATIONS
      called out in the JSON's evidence field: replay disables BEAR
      regime gate (no HMM) and BTC.D fast-rise filter -- both
      PERMISSIVE choices that make the replay an upper bound.

  [2] OPERATOR HALT NOTE. data/halt_state.json still
      {us:true, india:true, crypto:true} since 2026-05-22 15:41 UTC.
      No autonomous reset per prompt.

  [3]/[5]/[6] All deferred to this session or session 11.

Box state at session-9 close:
  - paper-crypto image: sha256:1d3a7ffadd385c77688724b43d6511d7cb821ca88c7a562c56a131b8877dc16b
  - metrics, watchdog: unchanged (session-7 deploy still current).
  - Operator halt set on all three markets.
  - Drawdown -33.4% (equity ~$87.45 vs peak $131.32). Cycles run every
    ~15 min, all crypto entries blocked by entry gate, no positions
    open.
  - foundation/state_bridge.py + foundation/positions.py now present
    on box (post-hotfix); USE_UNIFIED_LEDGER env flag is OFF so legacy
    per-strategy JSON state path is in use.

URGENT CONTEXT (unchanged from session 9): operator departs 2026-05-25
(in 2 days from session 9 = TOMORROW from session 10's perspective).
The 30-day paper soak (D.5) MUST start before then so the calendar
clock runs while operator is away. Track E
(docs/decisions/2026-05-22_live_flip_rebuild_plan.md Track E section)
is the shipping plan. Doctrine amendment at
docs/decisions/2026-05-23_doctrine_amendment_200_floor.md raises paper
floor $100 -> $200 for the reset. Runbook at
docs/runbooks/2026-05-23_operator_away_protocol.md.

THE BACKTEST RECOMMENDATION = PARTIAL. Per the hard-coded session-9
threshold rule, PARTIAL allows the session-11 reset to proceed (the
gate is "GO or PARTIAL = proceed; NO-GO = block"). The PARTIAL is
driven by the 50bps slippage flipping P&L sign -- the C3 edge is
razor-thin under realistic transaction costs. Operator was pinged
session 9 with this and the recommendation to re-halt C3 in the soak
if live P&L diverges from $0 by >$2 in the first week.

Goal of this session: ship PF5 stress tests + the reset script so
session 11 can run the reset on operator-departure day. Execute
in order:

  [0] PF5.6 D.1 AUTO-HALT ISOLATION (~45-90 min, MUST GO FIRST).
      Per docs/decisions/2026-05-22_live_flip_rebuild_plan.md A.4 PF5.6.
      Pure monkeypatch test, lowest blast radius. Write
      tests/preflight/test_pf5_6_d1_isolation.py with these scenarios:
        - A C3 strategy raising 3 consecutive exceptions auto-halts
          per risk/strategy_halt.py logic (verify it WRITES
          data/strategy_halt_state.json with c3=true).
        - Other strategies (C1, C6) continue to fire after C3 halts
          (verify by mocking generate_signals on each and asserting
          C1/C6 still called once after the C3 halt).
        - The halt is symbol-scoped not strategy-scoped (re-read the
          spec: confirm whether C3 halts ALL its symbols or just the
          erroring one; the test should match the spec).
        - Reset path: after operator calls reset_strategy("C3"),
          strategy_halt_state.json no longer has c3=true and C3
          generate_signals is reachable again.
      Use the existing test patterns at tests/test_strategy_halt.py
      for fixture / monkeypatch shape. Don't touch production code
      unless the test surfaces a real bug.

  [1] PF5.5 SLIPPAGE STRESS (~45-90 min). Per A.4 PF5.5 spec. Write
      tests/preflight/test_pf5_5_slippage.py. Verify that with
      simulated wider spread (e.g. mock the fetched orderbook to
      show a 100bps inside spread), C3's execution path correctly:
        - Either records the trade at the wider effective price
          (paper_trader.simulate_fill behavior) OR
        - Skips the trade if size_below_min_after_slippage logic
          exists (check execution/paper_trader.py for any such
          guard; if none, the test is documenting the absence).
      The harness's 50bps sensitivity result is +5.43 -> -5.72
      (P&L sign flip). PF5.5 is the in-strategy equivalent.

      For each test: monkeypatch the orderbook fetch in
      execution/paper_trader.py (find the call site, mock with a
      synthetic dict that has wider spread). Run a single buy + sell
      cycle through simulate_fill, assert the recorded fill price
      and ledger row match expectations.

  [2] scripts/reset_paper_book_200.py BUILD (~60-90 min, CRITICAL
      PATH for session 11). Per Track E.4 spec. Behavior:
        (a) Reads data/backtest_results/c3_60d_summary.json.
        (b) If recommendation == "NO-GO": print loud refusal +
            exit non-zero.
        (c) If recommendation in {"GO", "PARTIAL"}: proceed (print
            "PARTIAL: live monitoring contract from session 9"
            warning before continuing on PARTIAL).
        (d) Stop aaats-paper-crypto via docker compose stop on the
            box.
        (e) Remove the deployment_state-crypto-paper volume.
        (f) Recreate the volume with a $200 starting-capital seed.
            Likely path: create a fresh data/portfolio_state.json
            and data/state/* skeleton inside the volume mount with
            the $200 baseline. Look at how the volume gets seeded
            today (probably an entrypoint script in the Dockerfile
            or a first-run side effect of paper_trader.py); match
            that contract.
        (g) Clear operator halt for crypto via
            foundation/kill_switch.reset("crypto") (or kill.py CLI).
        (h) Restart aaats-paper-crypto. Confirm container reaches
            "running" status.
        (i) Wait up to 20 minutes for the first NONE-NONE digest
            (digest where Action needed is NONE). Write the digest
            timestamp to data/d5_day1_marker.json so subsequent
            sessions can see when D.5 started.
        (j) If digest doesn't reach NONE within 20 minutes, ROLL
            BACK: restore halt, restore previous volume snapshot if
            possible, write a failure marker, ping operator.
      Failing-then-passing tests at
      tests/test_reset_paper_book_200.py:
        - test_refuses_on_NO_GO (mock summary JSON with NO-GO -> exit 1)
        - test_proceeds_on_GO (mock GO -> reaches the "stop container"
          step before SSH layer; can stub out the SSH client)
        - test_proceeds_on_PARTIAL (mock PARTIAL -> proceeds with warning)
        - test_seeds_200_baseline (mock volume mount path -> $200 in
          portfolio_state.json after the seeding step)
      DO NOT actually run the script against the box in this session.
      Session 11 is the run window. The script should be dry-runnable
      with --dry-run that prints what it WOULD do.

  [3] STATE-BRIDGE GAP DOCTRINE NOTE (~15 min). The session-9
      hotfix exposed a class of bug: shipping a strategy file that
      imports a new local module without also shipping the imported
      module. Add a section to docs/conventions/deploy_discipline.md
      titled "Import-graph guard for SCP manifests" describing the
      gap and the recommended fix (walk the manifest's local imports,
      assert each imported module is either in-manifest or already
      on the box). The fix itself is session-10-optional; the doc
      note is the minimum.

  [4] LINT CHIP-AWAY (FILLER ONLY — only if [0]+[1]+[2]+[3] all
      done and >30 min slack). Continue from session-8's silent-
      except 71 baseline. Strong candidates:
        - monitoring/metrics_exporter.py 199/212/220 (confirm
          doctrine-correct silent-except before chipping)
        - markets/india/token_manager.py:136
        - markets/crypto/universe.py:226
        - health/watchdog.py:183
      For each: add log.debug body or annotate # noqa: silent-except
      with a one-line "why doctrine-correct" comment. Ratchet
      baseline.

  [5] D.5 day-1 PASSIVE CHECK. Will not fire pre-reset (operator
      halt set + drawdown -33.4%). Skip until post-reset session 11.

Constraints (unchanged from sessions 1-9):
  - No SCP deploy from dirty tree.
  - git pull --rebase BEFORE every push. Auto-cron on box pushes
    runtime/+data/+logs/ snapshots every 15 min; expect 30-60 such
    commits per session.
  - Push to GitHub at end of session.
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Keep paper-crypto running. Use --no-deps for rebuilds.
  - ASCII-only in deploy script print() calls.
  - aaats-watchdog and aaats-paper-crypto both depend on
    deployment_state-crypto-paper volume — session 11's reset script
    must be prepared to restart aaats-watchdog too OR confirm the
    volume rm/recreate works without breaking watchdog.
  - Pre-existing test failures NOT regressions:
    tests/test_dual_ledger_drift.py::test_dual_ledger_drift_bounded[runtime],
    tests/test_decision/test_consensus_voting.py::test_high_uncertainty,
    tests/test_ml/test_xgboost_ensemble.py (4 boundary cases),
    tests/test_india/test_angel_one_integration.py (credential errors).
    Don't try to fix unless that's your assigned scope.

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md.
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md.
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with the
    session 11 prompt. Session 11's critical path is: run
    scripts/reset_paper_book_200.py (the actual reset), validate the
    runbook end-to-end (PF5.7/PF5.8 if not in this session), confirm
    first NONE-NONE digest fires, file D.5 day-1 marker, send the
    operator-bye Telegram.
  - Commit + push.
  - OPERATOR PING (REQUIRED on these triggers):
    * reset_paper_book_200.py test failure that you can't resolve
      (session 11 can't run if the script is broken).
    * PF5.5 surfacing a real bug in execution/paper_trader.py.
    * Any deploy or hotfix to the box (none expected this session,
      but if [3] doctrine note grows into an actual import-graph
      guard and gets deployed, ping with the rollback baseline).
    Otherwise no ping needed.

Start with [0] PF5.6 D.1 isolation (~45-90 min, MUST GO FIRST), then
[1] PF5.5 slippage (~45-90 min), then [2] reset_paper_book_200.py
(~60-90 min CRITICAL PATH), [3] doctrine note (~15 min), [4] lint
only if slack. Total estimate: 3-4 hours of substantive work +
wrap-up. Session 11 (Day 3 = operator-departure day) takes the
session-10 reset script and RUNS it.

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents may
hit Write-tool permission denials. If you delegate, instruct subagents
to return content in their reply, not call Write directly.
```
