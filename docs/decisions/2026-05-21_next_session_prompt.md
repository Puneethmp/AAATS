# Next Claude Code session prompt (session 13 — operator-return review)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below on return from the away period. Session 12 closed all 3 must-verify pre-departure items + shipped one new fix (5+restarts/24h pager) + sent operator-bye. The soak is live.

**Updated:** 2026-05-23 (post session 12 — all C1-C5 exit gates GREEN). D.5 day-1 fired at 2026-05-23T12:46:32Z. First anomaly window backfilled (phantom_ena_crash_loop 13:29:44Z → 15:07:46Z). Divergence-watcher window: → 2026-05-30T12:46:32Z. D.5 soak day-30 ETA: 2026-06-22T12:46:32Z.

---

## Next autonomous session (mid-soak) — B.1.5 Phase 2

D.5 soak is day 4 of 30 (runs to 2026-06-22). The next autonomous session works on B.1.5 backtest-harness Phase 2, the gap-analysis-derived follow-up to session 13c (2026-05-27).

```
Context: AAATS B.1.5 backtest harness — Phase 2 (mechanical fixes +
data gap). D.5 soak ongoing (operator away). L11 baseline ok since
2026-05-27T08:01:50Z. Don't touch strategy/risk/halt code.

Background: session 13c (2026-05-27) found B.1.5 partly shipped for C3
(see docs/specs/b15_data_inventory.md + docs/specs/b15_backtest_harness.md
for the full inventory + design). First C3 run produced verdict=PARTIAL:
+$5.43 headline / Sharpe +1.52 but 50bps-slippage flips to -$5.72.
Three Phase-2 work items, in order:

1. sqrt(252) → sqrt(N/window_days*365) at two callsites:
   - monitoring/metrics_exporter.py:851 (window = 14d, fixed)
   - analytics/strategy_optimizer.py:125 (compute window from trade
     timestamps; extend SELECT)
   After landing, rebuild aaats-metrics container (use deploy_lib
   helpers per CLAUDE.md). aaats_rolling_sharpe_14d Grafana panel will
   jump to corrected (smaller-magnitude) values — that's expected.

2. Fetch ETH/USDT 1h 60d bars into data/historical/:
   venv\Scripts\python -c "from tools.backtest.historical_data import \
     fetch_ohlcv; fetch_ohlcv('ETH/USDT', '1h', days_back=60, \
     end_ts='2026-05-23T11:00Z')"
   Unblocks C1 + C6 replay scaffolding.

3. Optional stretch — begin C1 stat_arb replay scaffolding:
   - Extract pure helpers from trading/stat_arb.py (_compute_zs,
     _z_entry_allowed, _z_exit_allowed) into a clearly-marked pure
     block. Tiny, no behavior change.
   - tools/backtest/c1_replay.py mirroring c3_replay.py structure.
   Run against the now-present ETH+BTC cache; record verdict.

ESCALATE (stop) IF:
  - L11 effective_delta_usd has moved off ≈ 0 since 2026-05-27T08:01:50Z
  - The sqrt fix changes any *trading* logic (it shouldn't — these are
    monitoring + analytics only)
  - The ETH fetch hits a Binance rate limit or returns empty
  - C1 has no extractable pure helpers (would need a larger refactor —
    don't force it this session; reschedule to Phase 3 with proper scope)
```

When the operator returns, the operator-return paste-block below remains valid for that session's contract.

---

## Paste this block into the operator-return session

```
Context: AAATS operator-return review. The bot has been running the
D.5 30-day soak since 2026-05-23T12:46:32Z autonomously, through the
2026-05-23T13:29-15:07 phantom-ENA incident (recovered via session-11
hotfix) and with the session-12 anomaly-window counter + 5+restarts/24h
pager fix shipped before AFK departure. This session processes the
away-period queue, decides C.6 + C.7, optionally runs PF5.9 (deferred
from session 12), and stages the next move.

Session 11 + 12 shipped (REFERENCE — do not redo):

  Session 11 hotfix (commits c71291e, 11b0874, 86bc8d4, 4219651):
    Phantom-position fix. init_db.py schema mirror, paper_trader value
    + risk_action migration, IntegrityError re-raise on missing winner,
    C3+C6 ledger-first ordering, C1 stripped silent catch. Hotfix
    deploy archived broken paper_trades.db (id INTEGER) + orphan
    altcoin_reversion_state.json. tests/test_orphan_position_prevention.py
    pins all three layers.

  Session 12 [0] (commit 36e405f / paper-crypto b4a8f5906339, watchdog
  f828f7892163): D.5 anomaly-window counter. monitoring/daily_digest.py
  gains compute_soak_counter + enforce_anomaly_window_state +
  render_soak_counter_row. _mark_digest_sent now captures action_needed.
  Marker backfilled with phantom_ena_crash_loop window. 6 tests in
  tests/test_d5_soak_counter.py.

  Session 12 [1] (commit 660464b / watchdog 84a3e8c00302): 5+restarts/
  24h pager + auto-halt + persistent history. health/watchdog.py gains
  DAILY_RESTART_PAGER_THRESHOLD + _load/_save_persistent_restart_history
  + _check_daily_pager_threshold. ESCALATION upgraded to [PAGER] +
  critical. 5 tests in tests/test_pager_on_restart_storm.py + 11
  existing watchdog tests still green.

  Session 12 [2] B.2 P&L scan: branch (a) CLEAN. Only one valid C3
  TON/USDT BUY post-recovery, zero ENA phantom rows.

  Session 12 [3] PF5.9 DEFERRED to this session per D2 (time-tight).

  Pre-departure pager test: HTTP 200, message_id=2898.

  Operator-bye sent (cid 32ecfd0f-679d-4add-9b82-25e935c4911f).

  Session 13a (2026-05-24, pre-departure addendum — cron resilience):
    Built 4-layer auto-cron resilience after a false-positive 15h "blackout"
    investigation exposed real monitoring gaps. SHIPPED:
      L1: .github/workflows/liveness-monitor.yml (gated; needs operator
          to set TELEGRAM_* secrets + repo var LIVENESS_ENABLED=true)
      L2: /home/aaats/bin/aaats-autopush.sh v3 (heartbeat-first, 3x retry,
          Telegram alert) + /home/aaats/bin/aaats-cron-alert.sh
      L3: /home/aaats/bin/aaats-heartbeat-checker.sh (crontab */5; cooldown 1h)
      L4: /home/aaats/bin/aaats-diagnose.sh [--quick]
    Heartbeat canonical at /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json.
    Adversarial tests passed via /tmp staging (no prod disruption).
    Docs: docs/decisions/2026-05-24_auto_cron_resilience.md,
          docs/runbooks/auto_cron_recovery.md,
          docs/known_issues/2026-05-24_cron_blackout_false_positive.md.
    Rollback baseline: .rollback/2026-05-24_auto_cron_resilience/.
    Old v2 autopush retained at /home/aaats/bin/aaats-autopush.sh.v2.bak.20260524T095413Z.

  Session 13b (2026-05-27, mid-soak — L11 legacy-drift baseline):
    Closed the recurring L11 "capital invariant warn at -$8.5169" that had
    fired every cycle since L11 instrumentation shipped 2026-05-26. Drift
    diagnosed as legacy (constant -$8.5169 across 14+ readings with
    completely different open_notional/realized_pnl values), probable
    origin = 2026-05-23 phantom-ENA orphan-debit recovery or the
    2026-05-26 structural-fix deploy. Strategy code internally symmetric
    (no active leak). SHIPPED commits dcc6452 + 54117f0 on origin/main:
      - execution/paper_trader.py: _read_legacy_drift_baseline +
        raw/baseline/effective fields. Verdict gates on effective; v1
        delta_usd preserved for readers.
      - monitoring/metrics_exporter.py: 3 new gauges
        (aaats_capital_invariant_raw_delta_usd, _baseline_drift_usd,
        _effective_delta_usd). Existing delta_usd keeps emitting (with
        effective value).
      - data/capital_invariant_baseline.json: crypto=-$8.5169 with full
        audit metadata; india=0 (halted).
      - docs/known_issues/2026-05-27_l11_legacy_drift_baseline.md: audit
        + operator runbook for refreshing the baseline.
      - tools/operator/deploy_l11_baseline_2026_05_27.py: idempotent.
    Containers aaats-paper-crypto + aaats-metrics rebuilt. Live alert at
    08:01:50Z post-deploy: verdict=ok, raw=-8.5169, baseline=-8.5169,
    effective=0.0. All 4 smoke tests green. Rollback baseline at
    .rollback/2026-05-27_l11_baseline/MANIFEST.txt.
    Tiny secondary fix: deploy script's first attempt failed because
    ensure_remote_dirs(...) was passed dir paths instead of file paths
    (it mkdirs the PARENT of each input). Fixed to pass CHANGED_FILES
    .values() — pattern note for future deploy scripts.
    Also added !data/capital_invariant_baseline.json to .gitignore
    allow-list (matches existing pattern for halt_state.json etc.).

================================================================
PHASE 0 — Cron resilience + away-period liveness check (NEW 2026-05-24)
================================================================

  [0.1] FIRST COMMAND OF SESSION:
          git fetch origin main && git log origin/main --oneline -5
        The local `origin/main` ref is just a cache; reading `git log`
        without fetching is meaningless. The "15h blackout" false positive
        on 2026-05-24 originated from this exact mistake.

  [0.2] Read auto-cron heartbeat:
          ssh aaats@100.95.126.39 'bash /home/aaats/bin/aaats-diagnose.sh --quick'
        Expect status=ok, last_tick within ~15min, last_push within ~15min.
        If status=push_failed/fetch_failed or last_tick stale → L2/L3
        would have alerted to Telegram — confirm in [0.3] below.

  [0.3] Scan Telegram chat 1946109268 for any of these since 2026-05-25:
          - "AAATS LIVENESS ALERT" → L1 fired (box hard-down or push stream stale)
          - "AAATS CRON: auto-push failed 3x" → L2 retry exhausted
          - "AAATS CRON: fetch from origin failed" → L2 network/auth fail
          - "AAATS CRON: watchdog: ..." → L3 stale heartbeat
        Each maps to a triage flow in docs/runbooks/auto_cron_recovery.md.

  [0.4] Verify L1 (GitHub Actions liveness-monitor) is enabled:
          gh workflow list | grep "AAATS liveness"
          gh variable list | grep LIVENESS_ENABLED
        If `LIVENESS_ENABLED` is unset/false, the workflow is skipped
        (this is the pre-departure default — operator was expected to
        enable secrets and flip the variable). If enabled, view recent
        runs: `gh run list -w "AAATS liveness monitor" -L 10`.

  [0.5] If any alert fired during the away period, triage per runbook
        BEFORE proceeding to PHASE A. Liveness gaps are higher priority
        than pager queue review.

================================================================
PHASE A — Pager + digest queue review (DO AFTER PHASE 0, ~30-60 min)
================================================================

  [A.1] Read every Telegram pager queued since 2026-05-23T15:30Z.
        Source-of-truth: data/alerts_log.json on box (severity=critical
        rows + [PAGER] prefix). Cross-reference Telegram chat 1946109268
        if accessible. Tabulate:
          - timestamp
          - subsystem (which alert source)
          - what auto-action the pre-auth matrix took
          - whether operator intervention is now needed.
        Note: data/watchdog_state.json now holds the persistent 24h
        restart history. If 5+ shows up there, the pager fix triggered.

  [A.2] Read every daily digest from data/digests/ archive
        (alternative: data/digest_log.json index, which now includes the
        action_needed field per entry). Look for:
          - `Action needed != NONE` streaks (3+ in a row = was paged).
          - The C3 P&L since day-1 row in days 1-7 — did it stay within
            [-$2, +$2]? If exited, the watcher should have halted C3
            and that should appear in [A.1].
          - The "Soak day N of 30 (M digests excluded)" row — confirms
            the anomaly-window counter is working.
          - Strategy halt entries (any auto-halts during the period).

  [A.3] Read data/alerts_log.json full timeline. Tabulate by severity
        (info / warn / critical). Note resolution rate.

  [A.4] Check soak counter via:
          docker exec aaats-watchdog python -m monitoring.daily_digest --dry-run
        The Soak day N row gives the official counter. If counter << days
        since 2026-05-23, anomaly windows ate into it.

  Output of Phase A: one-page operator briefing with pager count,
  soak status, halted strategies, doctrine-level decisions if any.

================================================================
PHASE B — Soak verdict + B.2/B.3 evaluation
================================================================

  [B.1] D.5 verdict (C.6 gate):
          - If counter reached 30 → C.6 PASS.
          - If interrupted (counter << days_since_day1) → C.6 NOT YET;
            decide whether to restart day-1 or escalate.

  [B.2] B.2 evaluation (if 2026-05-29 was reached during the away
        period). Per docs/known_issues/2026-05-23_strategy_c3_post_b2.md.

  [B.3] B.3 4-week soak check (if it started). Compare final equity vs $200.
          - >= $200 → C.7 PASS.
          - <  $200 → C.7 FAIL → re-triage per C.7's failure-branch logic.

  [B.4] If C.6 + C.7 BOTH PASS: stage Track C live-flip preparation
        (operator-only decision; do not flip from this session).
        If either FAILS or NOT YET: produce NO-FLIP-YET briefing.

================================================================
PHASE C — PF5.9 adversarial test (deferred from session 12)
================================================================

  [C.1] PF5.9 adversarial restart-during-write test.
        Per feedback_adversarial_vs_verification_testing.md.

        tests/preflight/test_pf5_9_restart_during_write.py:
          - In-memory fixture mocking the C3 BUY emission path.
          - Inject failure between strategy_state.json write and
            paper_trader.record_trade — use a mock that raises
            BrokenPipeError or sqlite3.OperationalError mid-write to
            simulate the crash window.
          - Verify post-recovery state: either BOTH ledgers got the
            entry OR NEITHER. Never one without the other.
          - Failing-then-passing: checkout commit 1d3a7ff (pre-c71291e),
            run RED. HEAD: GREEN.

        If GREEN: log + close the bug class. If RED on HEAD: the fix
        is incomplete. Re-open the incident.

================================================================
PHASE D — Tree maintenance + commit
================================================================

  [D.1] Resolve any pager-driven decisions from Phase A.
  [D.2] Update Status logs (rebuild_plan.md, track_d_addendum.md).
  [D.3] Overwrite this file with the session-14 prompt. If C.6+C.7
        pass and operator decides live-flip → session-14 is Track C
        gate execution. Else → soak continuation.
  [D.4] Commit atomic per scope. git pull --rebase before push.

================================================================
CONSTRAINTS (unchanged from sessions 1-12)
================================================================

  - No SCP deploy from dirty tree.
  - git pull --rebase BEFORE every push.
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Use --no-deps for rebuilds.
  - Pre-existing test failures NOT regressions:
    test_dual_ledger_drift_bounded[runtime], test_high_uncertainty,
    test_xgboost_ensemble (4 cases), test_angel_one_integration,
    test_paper_loop::test_buy_blocked_by_risk_engine (state file
    pollution from prior tests).
  - Live-flip is operator-only (per autonomy contract).

================================================================
Reporting at session end
================================================================

  - Append to Status logs with operator-return verification results.
  - Overwrite this file with session-14 prompt.
  - Commit + push.
  - OPERATOR PINGS:
    * "Operator returned" Telegram (info-level).
    * Pager-level only on critical findings.
```

---

## Status log

- **2026-05-27 (session 13c — B.1.5 inventory + design + first C3 run, autonomous):**
  Mid-soak research session. Discovered the premise of the original B.1.5
  prompt was outdated: B.1.5 is partly shipped for C3 (~1,300 LOC across
  backtesting/, tools/backtest/, tests/) and 60d × 1H OHLCV cache exists
  at data/historical/. Reframed Phase 1 as gap analysis. Deliverables:
    - docs/specs/b15_data_inventory.md — what's on disk (file:line), what
      ETH gap blocks (C1 + C6), sqrt(252) scope clarified.
    - docs/specs/b15_backtest_harness.md — 5 subsections, GO/NO-GO floors
      pulled from doctrine, architecture (hybrid) acknowledged as locked,
      4-phase plan.
    - Ran existing C3 harness against cached window 2026-03-24→2026-05-23:
      verdict=**PARTIAL**. Headline 86 trades, +$5.43, Sharpe +1.52, 2/3
      profitable regimes. 50bps slippage flips to -$5.72 — slippage knife-edge
      is the actionable finding.
  Tag-along: committed deploy_lib docstring tightening clarifying
  ensure_remote_dirs accepts FILE paths (commit 4b5df88).
  Three open carry-forwards for the next session (Phase 2):
    1. Fix sqrt(252) → sqrt(N/window_days*365) in monitoring/metrics_exporter.py:851
       + analytics/strategy_optimizer.py:125 (live Grafana panel will jump).
    2. Fetch ETH/USDT 1H 60d bars into data/historical/.
    3. Begin C1 stat_arb replay scaffolding (mirror c3_replay pattern).

- **2026-05-27 (session 13b — mid-soak L11 baseline patch, autonomous):**
  Closed the recurring L11 capital invariant warn (-$8.5169 every cycle
  since 2026-05-26 instrumentation). Diagnosed as legacy drift (constant
  to 4dp across 14+ readings with widely varying open_notional + new
  trades, including a fresh position opened mid-deploy). Shipped commits
  dcc6452 (L11 baseline offset mechanism + 3 new Prometheus gauges) and
  54117f0 (audit memo + idempotent deploy script). aaats-paper-crypto +
  aaats-metrics rebuilt. Post-rebuild L11 reading 08:01:50Z:
  verdict=ok, raw=-8.5169, baseline=-8.5169, effective=0.0. All gauges
  visible at :9091/metrics. Rollback baseline at
  .rollback/2026-05-27_l11_baseline/MANIFEST.txt. Audit:
  docs/known_issues/2026-05-27_l11_legacy_drift_baseline.md.

  **Operator action queue (open items as of 2026-05-27):**
  1. **Rotate Grafana admin password** (open since 2026-05-26):
     /srv/aaats/secrets/grafana_admin_password is out of sync with the
     running Grafana instance — admin API auth rejected. Rotate when
     convenient. Source: CLAUDE.md "Deploy machinery gotchas" section.
  2. **Retrofit tools/operator/deploy_to_contabo.py to use deploy_lib**
     (open since 2026-05-26): the older general-purpose deploy script
     still uses raw tarball and reinvents helpers that deploy_lib now
     provides. Sprint follow-up. Source: CLAUDE.md gotchas list.
  3. **Investigate the legacy $8.5169 origin** (deferrable to post-soak):
     Most likely 2026-05-23T13:29Z phantom-ENA orphan-debit during the
     crash-loop recovery, or the 2026-05-26 structural-fix deploy. The
     audit memo (docs/known_issues/2026-05-27_l11_legacy_drift_baseline.md)
     has the diagnostic queries. Recommendation: forensic SQL pass over
     paper_trades.db with a "phantom debit" filter after soak closes.

- **2026-05-24 (session 13a — pre-departure cron resilience, autonomous):**
  Track D 4-layer build. False-positive 15h "blackout" investigation
  (workstation stale-fetch cache) catalyzed building the gaps it exposed.
  Shipped L1 GitHub Actions liveness monitor (gated on operator-set
  secrets), L2 aaats-autopush v3 (heartbeat-first + 3x retry + Telegram
  alert) + cron_alert.sh helper, L3 heartbeat-checker (crontab */5,
  1h cooldown), L4 diagnose.sh [--quick]. All 5 adversarial tests
  passed via /tmp staging — no prod disruption. Heartbeat canonical at
  /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json. Docs:
  decisions/2026-05-24_auto_cron_resilience.md, runbooks/auto_cron_recovery.md,
  known_issues/2026-05-24_cron_blackout_false_positive.md. Rollback baseline:
  .rollback/2026-05-24_auto_cron_resilience/MANIFEST.txt.
  Operator action required pre-soak-resumption: set repo secrets
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID + repo var LIVENESS_ENABLED=true
  (instructions in runbook). Until then, L1 is a no-op (the YAML file is
  shipped but the job is skipped).

- **2026-05-23 (session 12 — pre-departure verification, autonomous):**
  All three Cowork-surfaced items closed: [0] D.5 anomaly-window
  counter shipped (commit 36e405f / paper b4a8f59 + watchdog f828f78);
  [1] pager-during-crash diagnosed branch(c) + fix shipped (commit
  660464b / watchdog 84a3e8c); [2] B.2 scan CLEAN (branch a, 1 valid
  row); [3] PF5.9 deferred per D2. Pre-departure pager test PASSED
  (HTTP 200, message_id=2898). All C1-C5 exit gates GREEN.
  Operator-bye sent (cid 32ecfd0f). Total session ships: 11 new tests
  + 1 known-issue doc + 2 deploys + soak intact.

- **2026-05-23 (session 11 — phantom-position hotfix):** Three-layer
  bug closed (init_db schema, paper_trader IntegrityError handler,
  C3+C6 ledger-first ordering). Commits c71291e, 11b0874, 86bc8d4,
  4219651. tests/test_orphan_position_prevention.py — 6 tests green.

- **2026-05-23 (sessions 10+11):** D.5 reset to $200. day-1 fired
  2026-05-23T12:46:32Z. Divergence-watcher armed days 1-7.

- **D.5 day-30 ETA:** 2026-06-22T12:46:32Z (counter pauses during
  anomaly windows so could be later).

- **First anomaly window:** phantom_ena_crash_loop
  2026-05-23T13:29:44Z → 2026-05-23T15:07:46Z (~98 min).

---

## PHASE -1: pre-departure PnL grading (day 1 of D.5 soak)

Snapshot taken 2026-05-24T14:35Z, ~26h after D.5 reset (2026-05-23T12:46:32Z). Bot PnL +$0.189 on $200 baseline (+0.094%). CoinGecko 24h moves at snapshot: BTC +1.41%, ETH +2.17% — both clearly positive (>0.5%). Verdict: **MISS**. Market was up ~1.8% on average and the crypto book was effectively flat; defensive gates (C3/C6 sentiment, ML gate, regime detector) held entries off in a regime where being long would have paid. Not a bug — strategies are correctly conservative — but the ML gate threshold and entry-bias logic look over-defensive in calm-uptrend conditions. Worth a Track B post-return ticket to recalibrate against the full 30d soak distribution before changing anything. Do NOT touch thresholds mid-soak; we need the clean 30d baseline.
