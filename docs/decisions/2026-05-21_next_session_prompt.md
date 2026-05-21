# Next Claude Code session — pre-written prompt

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-21 (post session 1 A.0/B.0/D.0 ship).

---

## Paste this into the next Claude Code session

```
Context: AAATS rebuild sprint, session 2. Session 1 shipped A.0 + B.0 + B.0.5 + D.0 on the workstation; not yet deployed to the box. Status logs are in docs/decisions/2026-05-22_live_flip_rebuild_plan.md and docs/decisions/2026-05-21_track_d_reliability_addendum.md (search "2026-05-21 (session 1)").

Read first, in this order:
1. docs/decisions/2026-05-21_autonomy_contract.md — full technical autonomy still active. Do not ask for library / schema / retry / log format / test scaffolding picks. Do ask before money / risk / doctrine / broker / mode changes.
2. docs/decisions/2026-05-22_live_flip_rebuild_plan.md — read the "Status log" appendix entry for 2026-05-21 (session 1) before doing anything else.
3. docs/decisions/2026-05-21_track_d_reliability_addendum.md — same: read the latest Status log entry first.
4. docs/specs/reliability_failure_modes.md — D.0 catalog, 23 rows. D.1 and D.3 use this as the input set.
5. docs/known_issues/2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md, _c6_bollinger_range_diagnostic.md, _silent_strategy_audit.md — B.0/B.0.5 verdicts. B.1 triage decisions are already drafted in the silent-strategy audit's "Phase B.1" table; B.1 confirms them.
6. CLAUDE.md — deploy discipline still binding. Bind mounts: scripts/, data/, logs/ only.

Goal of this session: execute A.0 box deployment + B.1 triage confirmation + the highest-leverage Phase D.1 + D.3 in parallel.

A.0 box deployment (closes Phase A.0 fully — currently workstation-only):
  - Workstation already has the fix to production_readiness/metrics_aggregator.py (commit from session 1), MANIFEST + .pre snapshot at .rollback/2026-05-21_A0_readiness_scorer/.
  - Action: paramiko SCP the file to box (.tmp + mv -f), then `docker compose -f deployment/docker-compose.yml up -d --build --no-deps aaats-paper-crypto` per CLAUDE.md.
  - This is NOT bind-mounted (production_readiness/ is image-baked) so it requires the rebuild step.
  - Verify on box: `ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python scripts/evaluate_live_readiness.py'` — expect drawdown in [-15%, 0%] and uptime > 0%. Capture deployment_decision.json post-fix and confirm the -781% / 0% lines are gone.
  - Exit: PF1 can run clean on the metrics it controls; remaining blockers reflect real state (Win Rate, Total Trades), not arithmetic garbage.

B.1 triage confirmation (1 session):
  - The silent-strategy audit's Phase B.1 table already drafts the triage: C1=FIX, C2=KEEP, C3=PARAM-TUNE, C5b=HALT, C6=KEEP, N1–N7=OUT-OF-SCOPE.
  - Confirm by reading the three memos and the audit, then append a "B.1 decision" block to docs/decisions/2026-05-22_live_flip_rebuild_plan.md with each strategy → decision → rationale → next action (next action is the file:line + diff scope for FIX/PARAM-TUNE, not the actual code edit — that's B.2).
  - C1 cache invalidation can be done in this session if there's time (delete data/stat_arb_health.json on box; tail logs for the next recompute cycle). Operator-trivial; verify the strategy enters its run-cycle and either trades or honestly skips on a non-zero corr14d.
  - Exit: B.1 table merged into the plan; C1 cache invalidated and verified.

D.1 (per-strategy exception isolation):
  - Read docs/specs/reliability_failure_modes.md row 2 + addendum §"Phase D.1".
  - Wrap each strategy call in trading/paper_loop.py (and any sibling crypto runner) in its own try/except. On exception: log with strategy_id + cycle_id, increment a new Prometheus counter `strategy_exception_total{strategy=...}`, continue the cycle. Three consecutive exceptions in the same strategy → auto-HALT that strategy only (write to halt_state.json with reason).
  - Tests required: synthetic strategy that raises on cycle 3 — assert other strategies run on that cycle and after; assert auto-HALT on the 3rd consecutive exception; assert Telegram fires (mock the sender).
  - The trading/ tree is behavior-changing: write the failing test first per CLAUDE.md.
  - Exit: D.1 tests green; manual smoke on box shows the synthetic strategy halted alone.

D.3 (schema-drift assertions on startup):
  - Add pydantic models in state/schemas.py for the 5 JSON state files: heartbeat.json, halt_state.json, risk_engine_state.json, paper_positions.json, share_equality_mismatches.json.
  - Writers validate before write; readers validate after read; startup smoke runs all 5 reads and asserts. Mismatch → container refuses to start with a clear field-level error (not silent corruption).
  - Tests required: synthetic corrupted JSON → container fails fast; round-trip test per schema.
  - This closes ~9 of 23 catalog rows by construction (per the D.0 cross-cutting observation #2). High leverage.
  - Exit: every state file has a schema; CI runs a "schema sweep" test.

Constraints (unchanged from session 1):
  - No SCP deploy from dirty tree.
  - Push to GitHub at end of session.
  - No behavior change in trading/, execution/, risk/ paper paths without failing-then-passing test.
  - Keep paper-crypto running. If a container rebuild is needed, `--no-deps aaats-paper-crypto` only.
  - PAPER_MODE env var stays unused (Track A.1).

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md (A.0 box ship + B.1).
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md (D.1 + D.3).
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with the prompt for session 3 (likely D.2 watchdog + B.2 parameter sweeps + any A.1 prep).
  - Commit + push.
  - Ping operator only if something requires money/risk/doctrine decision.

Start by reading the six files listed above, then dispatch the parallel work. A.0 box deploy is sequential (SCP → rebuild → verify) but can run while D.1/D.3 work proceeds. B.1 is read-only.

KNOWN SUB-AGENT QUIRK from session 1: spawned Agents (via the Agent tool) hit Write-tool permission denials this workstation; main-context Edit/Write work fine. If you delegate to subagents, instruct them to return content in their reply, not call Write directly — the parent context will write the files.
```

---

## Why this is pre-written

Operator's standing rule `feedback_respond_as_prompt`: session reports + actionable follow-up should be delivered AS the next prompt, decisions baked in, no "want me to draft it?" round-trip. This file is that prompt for the next Claude Code session.

When that session finishes, it will overwrite this file with the prompt for the session after, so the chain is self-sustaining.
