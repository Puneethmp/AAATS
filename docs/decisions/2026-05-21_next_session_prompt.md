# Next Claude Code session prompt (session 7)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-23 (post session 6 — kill-trigger investigation closed; alerts-log writer + deploy-smoke drift + D.6 lint sweep + row 7/22 catalog all shipped to workstation).

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, session 7. Session 6 shipped everything in
its prompt to the workstation (NOT yet deployed to the box):
  [0a] Kill-trigger investigation CLOSED. Verdict primarily (d): the -15%
       market kill IS firing as a new-entry size gate, not a liquidation
       gate. Memo at docs/known_issues/2026-05-23_kill_trigger_investigation.md.
       Secondary finding: the three halt channels (data/halt_state.json
       operator-CLI, in-memory RiskEngine._halted_markets, and
       data/strategy_halt_state.json) are intentionally NOT synchronized.
       The session-4 inference "halt_state.json shows crypto:false,
       therefore kill is not firing" was wrong.
  [0b] Derivative fixes shipped to workstation:
       - trading/live_paper_runner.py:run_crypto now short-circuits on
         foundation.kill_switch.is_halted("crypto") (parity with run_india).
       - monitoring/daily_digest.py wording bands: -10/-15 "near",
         -15/-20 "past market-kill", <=-20 "past portfolio-kill".
       - CLAUDE.md "Kill-switch semantics" subsection added.
       - tests/test_kill_trigger_paths.py (5/5 green).
  [2]  Alerts-log writer (observability/alerts.py appends to
       data/alerts_log.json on every send_alert call, atomic .tmp+replace,
       UUID4 correlation_id) + daily_digest alerts_known=True branch +
       Action-needed trigger on alerts_open>=3. Tests:
       tests/test_alerts_log.py (11/11), digest band/alerts tests added.
  [2b] Deploy-smoke drift assertion at tools/operator/_digest_smoke.py +
       tests/test_operator/test_digest_smoke.py (9/9). Catches the
       session-5 volume-mount drift at build time.
  [3]  D.6 lint sweep at tools/lint/silent_except.py (silent-except +
       loguru-printf rules) + ratchet CI gate at
       tests/test_lint_silent_except.py + 268-hit baseline locked in
       tools/lint/silent_except_baseline.txt.
  [3b] Row 7 (metrics-exporter self-up gauge) added at
       monitoring/metrics_exporter.py::collect_self_up.
  [3c] Row 22 (dead-code resurrection guard) at
       tests/test_dead_code_guard.py.
  [4]  D.5 day-1 NOT triggered (Action needed != NONE today; clock
       remains parked).

Status logs at docs/decisions/2026-05-22_live_flip_rebuild_plan.md
"2026-05-23 (session 6)" and
docs/decisions/2026-05-21_track_d_reliability_addendum.md
"2026-05-23 (session 6)" have full ship reports.

Goal of this session: bundle the workstation-side changes into ONE
coordinated box deploy + execute B.2 (now eligible if today >= 2026-05-29)
+ any remaining lint cleanup. Execute in order:

  [0] BOX DEPLOY of session-6 workstation changes. Files to upload (via
      paramiko SCP, per CLAUDE.md deploy discipline):
        - trading/live_paper_runner.py (run_crypto is_halted gate)
        - monitoring/daily_digest.py (wording bands + alerts_log path)
        - observability/alerts.py (alerts-log writer)
        - foundation/kill_switch.py (noqa annotation only — no behavior change)
        - monitoring/metrics_exporter.py (collect_self_up)
        - tools/operator/_digest_smoke.py (new file — needed at deploy time)
        - tools/lint/silent_except.py + tools/lint/silent_except_baseline.txt
          (new — not strictly needed on box but cheap to ship)
      Rebuild containers (NO down):
        docker compose -f deployment/docker-compose.yml up -d --build --no-deps aaats-paper-crypto aaats-metrics aaats-watchdog
      Note: aaats-watchdog depends on monitoring/ which we ship via
      Dockerfile.watchdog COPY (already in place from session 5).
      Verify on box:
        - tail logs/aaats-paper-crypto for one cycle: confirm no errors,
          confirm no unexpected "Crypto market HALTED" lines (halt_state.json
          should still show crypto:false).
        - python -m monitoring.daily_digest --dry-run inside aaats-watchdog:
          confirm Equity line renders non-N/A AND the new band wording
          fires correctly at -33.4%.
        - confirm data/alerts_log.json starts populating on the next
          send_alert (any HALT or cycle exception will write a row).
      Rollback baseline at .rollback/2026-05-24_session7_kill_alerts_lint/MANIFEST.txt.

  [1] B.2 evaluation (ONLY if today >= 2026-05-29). Run the SQL queries
      in docs/known_issues/2026-05-23_strategy_c3_post_b2.md
      "Measurement protocol", compare against P1/P2/P3 pass / F1/F2/F3
      fail criteria, close or extend the memo. If inconclusive, build
      scripts/backtest_c3_param_sweep.py per the fallback section.
      If today < 2026-05-29, SKIP B.2; reorder to [2], [3].

  [2] C1 standalone kill-gate wire (deferred from session 6).
      Add apply_kill_switch_gate call site at trading/stat_arb.py:478,
      parity with C3 (altcoin_reversion.py:508) and C6
      (bollinger_range.py:256). Failing-then-passing test:
      tests/test_stat_arb_kill_gate.py — assert that with paper-crypto
      at -33% drawdown, run_stat_arb_crypto does NOT open a new position
      even when z > entry_z. Ship the patch + test in one commit.

  [3] Lint cleanup chip-away (~1-2 hours). Pick the top-15 highest-leverage
      hits from `python -m tools.lint.silent_except`. Strong candidates:
        - loguru-printf hits in execution/paper_executor.py (lines 126,
          144, 150, 217, 268, 276, 294) — these fire on every trade
          and are the original Row 17 motivation.
        - silent-except in execution/idempotency.py:179/191/200 (sqlite
          OperationalError swallow) — should at least log.
      For each: convert printf `%s` to `{}` format OR add proper logging
      to silent-except. Update tools/lint/silent_except_baseline.txt
      downward. Run tests after each batch.

  [4] D.5 day-1 passive check. If today's first digest fires
      "Action needed: NONE", note in the status log that day-1 has
      begun. Otherwise skip.

Constraints (unchanged from sessions 1-6):
  - No SCP deploy from dirty tree.
  - `git pull --rebase` BEFORE every push. Auto-cron on box pushes
    runtime/+data/+logs/ snapshots every 15 min; expect 30-60 such
    commits per session.
  - Push to GitHub at end of session.
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Keep paper-crypto running. Use `--no-deps` for rebuilds.
  - ASCII-only in deploy script print() calls -- strip log output to
    ASCII before printing.
  - Watchdog reads state-crypto-paper RO; the daily digest fires once
    per IST calendar day at >= 09:00 IST.
  - aaats-watchdog and aaats-paper-crypto both depend on
    deployment_state-crypto-paper volume.

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md.
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md.
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with the
    session 8 prompt.
  - Commit + push.
  - Ping operator on: deploy-smoke catching a real regression
    (drift assertion fires), B.2 fail-condition triage, or kill-switch
    events (drawdown more negative than -35%, share-equality delta
    > $0.50, container failing to start). Otherwise no ping needed.

Start with [0] box deploy. The longer the workstation-side changes sit
undeployed, the higher the chance an auto-cron commit drifts onto the
same lines. Estimate: 30-45 min for deploy + verify, then [1] if
eligible or [2]+[3] otherwise.

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents may hit
Write-tool permission denials. If you delegate, instruct subagents to
return content in their reply, not call Write directly.
```
