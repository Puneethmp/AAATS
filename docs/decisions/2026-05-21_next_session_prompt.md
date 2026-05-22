# Next Claude Code session — pre-written prompt

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-21 evening (Cowork review of session 1 ship report; three surfaced findings folded into session 2 scope — see § "Surfaced from session 1" inside the block below).

---

## Paste this into the next Claude Code session

```
Context: AAATS rebuild sprint, session 2. Session 1 shipped A.0 + B.0 + B.0.5 + D.0 on the workstation; not yet deployed to the box. Status logs are in docs/decisions/2026-05-22_live_flip_rebuild_plan.md and docs/decisions/2026-05-21_track_d_reliability_addendum.md (search "2026-05-21 (session 1)").

Surfaced from session 1 (folded into session 2 scope, do NOT re-investigate from scratch — read the session 1 status logs first):
- NEW dual-ledger drift: runtime/paper_positions.json vs data/paper_positions.json — two writers, two file paths, contents disagree. Pre-existing dual_equity_ledger_debt was data/paper_positions.json vs paper_trades.db; this adds a third file to the picture. Quick identify-and-document task in A.0 box-deploy follow-up.
- share_equality_mismatches.json is NOT empty in production (C3 TON/FET counters, pre-existing). The 2026-05-21 NO-GO doc claimed it was clean; that was wrong. Audit the alert chain: did Telegram fire for those counters? If the chain is broken, that's a Track D row not previously flagged.
- C1 stat_arb (silent strategy) is the highest-leverage near-term action: poisoned `corr14d=0.000` cache despite z=+4.74 signal. One-file-delete fix. Promoted from "if time permits" to FIRST ACTION ITEM of session 2.
- C3 PARAM-TUNE input: `BTC_DOM_FAST_RISE` constant declared but never read in `_entry_allowed`. Symbol-halt math: residual without top-5 losers (OP, ARB, PUMP, FET, LUNC) = -$1.216/9d (vs -$5.63/9d as-is). Recommended B.1 verdict: PARAM-TUNE + symbol-halt combined, reversible.

Read first, in this order:
1. docs/decisions/2026-05-21_autonomy_contract.md — full technical autonomy still active. Do not ask for library / schema / retry / log format / test scaffolding picks. Do ask before money / risk / doctrine / broker / mode changes.
2. docs/decisions/2026-05-22_live_flip_rebuild_plan.md — read the "Status log" appendix entry for 2026-05-21 (session 1) before doing anything else.
3. docs/decisions/2026-05-21_track_d_reliability_addendum.md — same: read the latest Status log entry first.
4. docs/specs/reliability_failure_modes.md — D.0 catalog, 23 rows. D.1 and D.3 use this as the input set.
5. docs/known_issues/2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md, _c6_bollinger_range_diagnostic.md, _silent_strategy_audit.md — B.0/B.0.5 verdicts. B.1 triage decisions are already drafted in the silent-strategy audit's "Phase B.1" table; B.1 confirms them.
6. CLAUDE.md — deploy discipline still binding. Bind mounts: scripts/, data/, logs/ only.

Goal of this session: execute (in order of leverage) [0] C1 cache invalidation → [1] A.0 box deployment + dual-ledger drift identification + share_equality alert-chain audit → [2] B.1 triage confirmation with C3 combined verdict → [3] D.1 per-strategy exception isolation → [4] D.3 schema-drift assertions. Items [1] and [3]+[4] are parallel-safe; B.1 is read-only and can interleave.

[0] C1 cache invalidation (FIRST ACTION ITEM — cheapest, highest-leverage):
  - On box: `docker exec aaats-paper-crypto rm -f /app/data/stat_arb_health.json` (verify path with `docker exec aaats-paper-crypto ls /app/data/stat_arb*`).
  - Tail container logs for the next recompute cycle (interval is in trading/paper_loop.py — likely 5 min): `docker logs -f --tail 100 aaats-paper-crypto | grep -iE "stat_arb|c1|corr14d"`.
  - Verify: corr14d in the next state-write is non-zero; C1 either trades (z=+4.74 should fire) or honestly skips with a logged reason that is NOT the corr14d=0.000 false-floor.
  - If C1 trades within 60 minutes: capture the trade row, halt this sub-task, proceed to [1]. If not: document the skip reason in docs/known_issues/2026-05-21_c1_post_cache_invalidation.md and continue.
  - Exit: C1 cache cleared, behaviour observed, finding logged.

[1] A.0 box deployment (closes Phase A.0 fully — currently workstation-only):
  - Workstation already has the fix to production_readiness/metrics_aggregator.py (commit from session 1), MANIFEST + .pre snapshot at .rollback/2026-05-21_A0_readiness_scorer/.
  - Action: paramiko SCP the file to box (.tmp + mv -f), then `docker compose -f deployment/docker-compose.yml up -d --build --no-deps aaats-paper-crypto` per CLAUDE.md.
  - This is NOT bind-mounted (production_readiness/ is image-baked) so it requires the rebuild step.
  - Verify on box: `ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto python scripts/evaluate_live_readiness.py'` — expect drawdown in [-15%, 0%] and uptime > 0%. Capture deployment_decision.json post-fix and confirm the -781% / 0% lines are gone.
  - SUB-TASK 1.a — runtime/ vs data/ paper_positions.json drift identification:
      * grep workstation tree for writers: `rg --no-heading -n "paper_positions" --type py` and classify each hit as runtime/ writer, data/ writer, or reader. Output: docs/known_issues/2026-05-21_paper_positions_writer_drift.md with the call graph.
      * Do NOT fix in this session — that's a Track A.0 follow-up that needs to land alongside D.3 schema work. Just identify, document, and decide which path is canonical (recommendation surfaces in the memo).
  - SUB-TASK 1.b — share_equality_mismatches.json alert-chain audit:
      * Cat the file on box; record current C3 TON/FET counter values.
      * Check Grafana alert history (`docs/known_issues/` may have a runbook; otherwise query the Grafana API) for `share_equality_mismatch` rule fires in the last 9 days.
      * If no Telegram alerts were sent despite non-zero counters: add a new row to docs/specs/reliability_failure_modes.md ranked S1 ("share-equality alert chain broken in production despite synthetic test passing 2026-05-16"). This is a new D-track input that D.0 missed.
      * If alerts WERE sent and operator missed them: document in the same memo as an operator-cognition issue (D.4 daily digest covers this — note the link).
  - Exit: PF1 can run clean on the metrics it controls; remaining blockers reflect real state (Win Rate, Total Trades), not arithmetic garbage. Two new docs/known_issues memos exist.

[2] B.1 triage confirmation:
  - Silent-strategy audit's Phase B.1 draft: C1=FIX (already executed in [0]), C2=KEEP, C3=PARAM-TUNE, C5b=HALT, C6=KEEP, N1–N7=OUT-OF-SCOPE.
  - REVISE C3 verdict to "PARAM-TUNE + symbol-halt (combined)": (a) wire BTC_DOM_FAST_RISE into _entry_allowed (file:line scope only — no code edit in this session, that's B.2); (b) add OP/USDT, ARB/USDT, PUMP/USDT, FET/USDT, LUNC/USDT to C3 symbol deny-list (residual = -$1.216/9d per session 1's symbol-halt math). Reversible; safer than full C3 HALT.
  - Append "B.1 decision" block to docs/decisions/2026-05-22_live_flip_rebuild_plan.md with each strategy → decision → rationale → next action (file:line + diff scope for FIX/PARAM-TUNE).
  - Exit: B.1 table merged; C1 status from [0] documented in the same block.

[3] D.1 (per-strategy exception isolation):
  - Read docs/specs/reliability_failure_modes.md row 2 + addendum §"Phase D.1".
  - Wrap each strategy call in trading/paper_loop.py (and any sibling crypto runner) in its own try/except. On exception: log with strategy_id + cycle_id, increment a new Prometheus counter `strategy_exception_total{strategy=...}`, continue the cycle. Three consecutive exceptions in the same strategy → auto-HALT that strategy only (write to halt_state.json with reason).
  - Tests required: synthetic strategy that raises on cycle 3 — assert other strategies run on that cycle and after; assert auto-HALT on the 3rd consecutive exception; assert Telegram fires (mock the sender).
  - The trading/ tree is behavior-changing: write the failing test first per CLAUDE.md.
  - Exit: D.1 tests green; manual smoke on box shows the synthetic strategy halted alone.

[4] D.3 (schema-drift assertions on startup):
  - Add pydantic models in state/schemas.py for the 5 JSON state files: heartbeat.json, halt_state.json, risk_engine_state.json, paper_positions.json, share_equality_mismatches.json.
  - IMPORTANT (session 1 finding): share_equality_mismatches.json is non-empty in production (C3 TON/FET counters). The schema must support a non-empty mismatches map (likely a Dict[str, int] keyed by "symbol_a|symbol_b" → count). Do NOT model it as an empty-only sentinel.
  - paper_positions.json schema must accommodate the runtime/ vs data/ writer drift from sub-task 1.a — if [1] concludes there are two distinct shapes, model both and assert the canonical path matches the canonical shape; flag the other path as legacy in a docstring.
  - Writers validate before write; readers validate after read; startup smoke runs all 5 reads and asserts. Mismatch → container refuses to start with a clear field-level error (not silent corruption).
  - Tests required: synthetic corrupted JSON → container fails fast; round-trip test per schema; explicit round-trip with the production share_equality_mismatches.json captured in [1.b] as a fixture.
  - This closes ~9 of 23 catalog rows by construction (per the D.0 cross-cutting observation #2). High leverage.
  - Exit: every state file has a schema; CI runs a "schema sweep" test; production share_equality fixture round-trips clean.

Constraints (unchanged from session 1):
  - No SCP deploy from dirty tree.
  - Push to GitHub at end of session.
  - No behavior change in trading/, execution/, risk/ paper paths without failing-then-passing test.
  - Keep paper-crypto running. If a container rebuild is needed, `--no-deps aaats-paper-crypto` only.
  - PAPER_MODE env var stays unused (Track A.1).

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md (A.0 box ship + B.1 + C1 cache outcome + dual-ledger drift finding).
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md (D.1 + D.3 + share-equality alert-chain audit outcome).
  - If [1.b] surfaced a broken alert chain: add the new row to docs/specs/reliability_failure_modes.md and note it in the addendum status log.
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with the prompt for session 3 (likely D.2 watchdog + B.2 parameter sweeps on the C3 tune + A.1 state-isolation prep + paper_positions writer-drift fix if 1.a's recommendation is approved).
  - Commit + push.
  - Ping operator only if something requires money/risk/doctrine decision. Specifically: do NOT ping for [0]/[1]/[1.a]/[1.b]/[2]/[3]/[4] outcomes unless one of them surfaces a kill-switch event (drawdown > -15%, share-equality delta > $0.50, or container failing to start after rebuild).

Start with [0] C1 cache invalidation — cheapest, highest-leverage, sets up B.1 verdict on C1. Then dispatch [1] (sequential: SCP → rebuild → verify → 1.a + 1.b sub-tasks), [3] D.1, and [4] D.3 in parallel. B.1 confirmation is read-only and can interleave between blockers. Use Sonnet for the implementation work in [3] and [4]; [1] is also Sonnet-grade. Only escalate to Opus if a non-obvious bug appears.

KNOWN SUB-AGENT QUIRK from session 1: spawned Agents (via the Agent tool) hit Write-tool permission denials this workstation; main-context Edit/Write work fine. If you delegate to subagents, instruct them to return content in their reply, not call Write directly — the parent context will write the files.
```

---

## Why this is pre-written

Operator's standing rule `feedback_respond_as_prompt`: session reports + actionable follow-up should be delivered AS the next prompt, decisions baked in, no "want me to draft it?" round-trip. This file is that prompt for the next Claude Code session.

When that session finishes, it will overwrite this file with the prompt for the session after, so the chain is self-sustaining.
