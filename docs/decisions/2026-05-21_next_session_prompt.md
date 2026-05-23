# Next Claude Code session prompt (session 6)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-23 (post session 5 — [0] reconciler Option A + [1] A.1 box deploy + [2] D.4 daily digest implementation all shipped).

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, session 6. Session 5 shipped everything in
its prompt:
  [0] Reconciler Option A (C1_stat_arb added to Source B exclusion SQL) +
      halt_on_critical=True re-enabled. Verified clean on box: "Reconciliation
      clean | checked=7 positions across crypto", zero BTC/ETH HALT lines,
      RestartCount=0. Image sha256:7a32d03ecfc9...
  [1] A.1 state isolation BOX DEPLOY. Per-mode mounts live; legacy
      deployment_state-crypto preserved as 7-day rollback baseline.
      Verified: "Risk engine peak loaded from /app/data/state-paper/
      risk_engine_state.paper.json: $131.32".
  [2] D.4 daily digest IMPLEMENTED + first live send confirmed on
      Telegram. Watchdog dispatches at 09:00 IST daily. cycle_log
      SQLite table now feeds the Operational "Cycles run" field.
  Status logs at docs/decisions/2026-05-22_live_flip_rebuild_plan.md
  and docs/decisions/2026-05-21_track_d_reliability_addendum.md have
  full ship reports under "2026-05-23 (session 5)".

Two session-5 mid-deploy fixes worth knowing about (NO follow-up needed
this session; they're captured here for orientation):
  - Watchdog now mounts deployment_state-crypto-paper:/app/data/state-paper:ro
    so the digest can resolve equity/peak/dd. The first live digest
    reported "Action needed: NONE" against the known -33% drawdown
    until this mount was added. Compose change committed.
  - Dockerfile.watchdog now COPYs monitoring/ so the digest module is
    in the watchdog image. Already deployed.

PF1 score still nominal-fail because the real strategy state hasn't
changed: Win Rate 28.3%, Drawdown -33.4%. The drawdown reflects
mark-to-market on open C3 positions; B.3 soak is the path to a NONE
digest, not a code change in session 6.

Surfaced from session 5 (folded into session 6 scope, do NOT re-investigate
from scratch):
- B.2 paper-shadow validation is AWAITING DATA: 7-day window from the
  C3 patch deploy ends 2026-05-29T15:00Z. Re-evaluate per the locked
  protocol in docs/known_issues/2026-05-23_strategy_c3_post_b2.md
  IF today's date is >= 2026-05-29. Otherwise skip B.2 entirely.
- D.5 30-day soak: NOT YET STARTED. Defined start is the first day the
  digest fires with "Action needed: NONE". Today's digest correctly
  reports drawdown -33.4% breach, so day-1 cannot begin until B.3
  resolves the drawdown.
- Alerts log writer is a small queued item: the digest's "Alerts fired"
  row is currently always N/A pending an observability.alerts.send_alert
  wrapper that appends to data/alerts_log.json. ~1 Haiku session if
  picked up.
- Deploy-smoke drift assertion: the next deploy-script enhancement
  should check that the digest renders non-N/A equity post-deploy
  (caught by hand in session 5 when the volume mount was missing).
  Small queued item.
- New profitability gate C.7 (added 2026-05-23): the final-week equity
  of the B.3 4-week soak must be >= the soak's starting equity. See
  docs/decisions/2026-05-22_live_flip_rebuild_plan.md §"Track C - Flip
  gate" C.7 for the full criterion. Does not change session-6 scope
  unless B.2 forces a B.1 re-triage.

Read first, in this order:
1. docs/decisions/2026-05-21_autonomy_contract.md — full technical
   autonomy still active.
2. docs/decisions/2026-05-22_live_flip_rebuild_plan.md — read the
   "Status log" entry for 2026-05-23 (session 5) AND the B.1 triage
   table immediately below it.
3. docs/decisions/2026-05-21_track_d_reliability_addendum.md — read the
   2026-05-23 (session 5) entry for D.4 ship status + the deferred
   D.6/alerts-log/drift-assertion list.
4. docs/known_issues/2026-05-23_strategy_c3_post_b2.md — B.2
   measurement protocol (skip if before 2026-05-29).
5. CLAUDE.md — deploy discipline still binding.

Goal of this session: execute (in order of leverage):
  [0] B.2 evaluation (ONLY if today >= 2026-05-29). Run the SQL queries
      in the C3 memo §"Measurement protocol", compare against P1/P2/P3
      pass / F1/F2/F3 fail criteria, close or extend the memo. If
      inconclusive, build scripts/backtest_c3_param_sweep.py per the
      fallback section.
  [1] Alerts-log writer + deploy-smoke drift assertion (the two small
      queued items from session 5). Adds the missing inputs to the
      Action-needed trigger matrix and tightens deploy-script
      correctness.
  [2] D.6 lint sweep (proposed in session 1 D.0). Implement an
      AST-based check that flags `except OSError: pass` and
      `except Exception: pass` patterns in writer paths. Bundle with
      the row-7/17/22 catalog items if scope allows. ~1 Sonnet session.
  [3] D.5 soak day-1 (passive). When the first digest fires with
      "Action needed: NONE", confirm data/digests/<date>.txt landed
      and the operator received the Telegram. No code required; this
      is just monitoring.

If today < 2026-05-29 (B.2 not yet eligible), reorder to [1], [2],
[3], dropping [0].

[1] Alerts-log writer + deploy-smoke drift assertion:
  - observability/alerts.py: wrap send_alert to also append a JSON line
    to data/alerts_log.json with timestamp, market, severity (parse
    from the message body or accept as kwarg), message body, and
    correlation_id (uuid). Atomic .tmp+replace write.
  - monitoring/daily_digest.py: enable the alerts_known=True branch in
    build_ops_section; read data/alerts_log.json, compute fired / open
    / resolved counts over the 24h window. Add to the Action-needed
    trigger matrix: alerts_open >= 3 fires the action line.
  - tests/test_alerts_log.py: writer test (atomic write, append-only,
    no race-corruption on tmp+replace under simulated SIGINT mid-write).
  - Update tests/test_daily_digest.py golden output to include the
    alerts_known=True case.
  - Deploy-smoke drift assertion: in any new deploy script that touches
    the digest path, add a smoke step that runs the dry-run, parses
    the output, and asserts "Equity:" line does NOT contain "N/A"
    when risk_engine_state.paper.json exists. Add a helper at
    tools/operator/_digest_smoke.py if reusable.

[2] D.6 lint sweep:
  - tools/lint/silent_except.py: AST walk that flags
    `except <Exception-type>: pass` patterns. Whitelist
    `# noqa: silent-except` for the audit_trail / kill_switch paths
    where silent failure is doctrine-correct.
  - Run across the repo; expect dozens of hits. Triage into:
    (a) writer paths -- fix to log + propagate (D.6 hard targets)
    (b) reader paths -- log + return None (acceptable)
    (c) audit/halt paths -- keep with noqa annotation
  - Add to CI: pytest plugin or pre-commit hook (whichever doesn't
    require new infrastructure -- the repo doesn't currently use
    pre-commit; pytest plugin is the lighter touch).
  - Row 7 (metrics-exporter target-down): add a Prometheus
    self-up gauge to monitoring/metrics_exporter.py + alert rule.
  - Row 17 (loguru printf-format recurrence-prone): the lint sweep
    above catches most of this; add `# {} not %s` to the lint rule.
  - Row 22 (dead-code SELL-share recompute resurrection risk):
    delete the dead path; add a tests/test_dead_code_guard.py grep
    test that fails if the function name reappears.

[3] D.5 soak day-1 (passive, do nothing unless triggered):
  - The watchdog already archives every digest to data/digests/<date>.txt
    via build_and_send_digest. The 30-day clock starts when:
    (a) The most recent digest body contains "Action needed: NONE".
    (b) data/digests/ has at least one file dated today.
  - If both are true on session start: note in the status log that
    D.5 day-1 has begun. Otherwise skip.

Constraints (unchanged from sessions 1+2+3+4+5):
  - No SCP deploy from dirty tree.
  - `git pull --rebase` BEFORE every push. Auto-cron on box pushes
    runtime/+data/+logs/ snapshots every 15 min; expect 30-60 such
    commits per session.
  - Push to GitHub at end of session.
  - No behavior change in trading/, execution/, risk/ paper paths
    without failing-then-passing test.
  - Keep paper-crypto running. Use `--no-deps aaats-paper-crypto`
    for rebuilds; the watchdog has no siblings.
  - ASCII-only in deploy script print() calls -- strip log output to
    ASCII before printing (the patched _run helper in
    scripts/deploy_session5_*.py is the reference pattern).
  - Watchdog reads state-crypto-paper RO; the daily digest fires once
    per IST calendar day at >= 09:00 IST. Do not change the dispatch
    cadence without operator approval (would change D.5 semantics).
  - aaats-watchdog and aaats-paper-crypto both depend on
    deployment_state-crypto-paper now -- a volume drop or rename
    breaks both. Reference: docs/decisions/2026-05-22_state_isolation_design.md.

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md
    ([0]+[1]+[2] ship reports as applicable).
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md
    ([1] alerts-log, [2] D.6 if shipped, [3] D.5 day-1 if triggered).
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with the
    session 7 prompt.
  - Commit + push.
  - Ping operator on: B.2 fail-condition triage ([0]), drift assertion
    catching a real bug in deploys, or kill-switch events (drawdown
    more negative than -30%, share-equality delta > $0.50, container
    failing to start). Otherwise no ping needed.

Start with B.2 (if eligible) since it has the date constraint; if not
eligible, start with [1] alerts-log writer (~3 hours of work for the
writer + tests + digest integration + dry-run). [2] D.6 is the bulk of
the session if B.2 isn't eligible.

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents may hit
Write-tool permission denials. If you delegate, instruct subagents to
return content in their reply, not call Write directly.
```
