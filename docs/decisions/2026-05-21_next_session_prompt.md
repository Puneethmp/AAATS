# Next Claude Code session prompt (session 3)

**Purpose:** Per `feedback_respond_as_prompt.md` — operator pastes the block below into the next Claude Code session. No further decisions needed before work starts.

**Updated:** 2026-05-22 (post session 2 — A.0 box + C1 cache + B.1 + D.1 + D.3 all shipped).

---

## Paste this block into the next Claude Code session

```
Context: AAATS rebuild sprint, session 3. Session 2 shipped everything in its prompt
(C1 cache invalidation, A.0 box deploy, B.1 triage confirmation, D.1 per-strategy
isolation, D.3 schema-drift assertions, plus the 1.a + 1.b memos). The status
logs at docs/decisions/2026-05-22_live_flip_rebuild_plan.md and
docs/decisions/2026-05-21_track_d_reliability_addendum.md have full session 2
ship reports under "2026-05-22 (session 2)". The D.1+D.3 code is on the
workstation only — box still runs the pre-session-2 image of
trading/live_paper_runner.py and monitoring/metrics_exporter.py (A.0 metrics_aggregator
fix IS on box).

Surfaced from session 2 (folded into session 3 scope, do NOT re-investigate from scratch):
- ACTIVE BUG: monitoring/heartbeat_monitor.py:142 `Heartbeat(**hb_data)` reads the
  legacy nested-per-market schema, but the runner writes the flat schema directly
  at trading/live_paper_runner.py:1873-1882. PF1 uptime is stuck at 0% because of
  this. D.3 catches the *schema* on startup; this session removes the *legacy reader*
  so PF1 uptime reports correctly. Scope: rewrite get_heartbeat / get_all_heartbeats /
  is_alive on the flat schema. Caller audit: production_readiness/metrics_aggregator.py
  is the only caller (verified session 2). One-file fix, deferred to this session.
- C3 PARAM-TUNE + symbol-halt is decided (B.1 table merged in plan doc). The actual
  patch is B.2 scope. File:line scope already documented in the B.1 table — pick it
  up directly.
- Box has NOT been redeployed with D.1+D.3 yet. SCP + rebuild needed once the
  legacy-heartbeat-reader fix lands (so all three changes flow in one rebuild).
- runtime/paper_positions.json is workstation-only debug scratch; delete it (memo
  at docs/known_issues/2026-05-22_paper_positions_writer_drift.md has the case).

Read first, in this order:
1. docs/decisions/2026-05-21_autonomy_contract.md — full technical autonomy still
   active.
2. docs/decisions/2026-05-22_live_flip_rebuild_plan.md — read the "Status log" entry
   for 2026-05-22 (session 2) AND the B.1 triage table immediately after.
3. docs/decisions/2026-05-21_track_d_reliability_addendum.md — read the 2026-05-22
   (session 2) entry for D.1+D.3 details.
4. docs/known_issues/2026-05-22_paper_positions_writer_drift.md — 1.a memo.
5. docs/known_issues/2026-05-22_share_equality_alert_chain.md — 1.b memo (no action
   needed; chain is healthy).
6. CLAUDE.md — deploy discipline still binding.

Goal of this session: execute (in order of leverage):
  [0] Legacy heartbeat reader removal (one-file fix; unblocks PF1 uptime > 0%).
  [1] SCP-deploy D.1 + D.3 + heartbeat-reader fix to box in one rebuild.
      Verify with `docker exec aaats-paper-crypto python scripts/evaluate_live_readiness.py`
      — expect uptime > 0% (real value, not 0% arithmetic).
  [2] B.2 — execute the C3 PARAM-TUNE + symbol-halt patch (file:line scope is in
      the B.1 table). One-file edit in trading/altcoin_reversion.py. Run a 7-day
      backtest if extant; otherwise paper-shadow.
  [3] D.2 (heartbeat watchdog) — new sidecar container that tails data/heartbeat.json
      and auto-restarts the trading container on stale heartbeat. Parallel-safe with
      B.2. Specs in docs/decisions/2026-05-21_track_d_reliability_addendum.md §"Phase D.2".
  [4] A.1 — state isolation prep (per-mode risk_engine_state files). Read-only design
      task this session; implementation in session 4.

[0] Legacy heartbeat reader removal (FIRST ACTION ITEM):
  - File: monitoring/heartbeat_monitor.py
  - Rewrite get_heartbeat / get_all_heartbeats / is_alive to read the FLAT schema
    matching state/schemas.HeartbeatSchema. The flat shape is what the runner has been
    writing since 2026-05-15+; the nested form has been dead code since then.
  - Touch points:
    * production_readiness/metrics_aggregator.py:241-246 — caller. Confirm it still
      returns a sensible reliability ratio post-fix (single-market freshness check).
    * heartbeat_monitor.HeartbeatMonitor.emit_heartbeat at lines 80-100 — REMOVE.
      Runner writes the flat shape directly; the dataclass-emit path is dead.
    * Any remaining caller of emit_heartbeat — grep first; deprecate cleanly.
  - Tests: tests/test_heartbeat_monitor.py — round-trip on the flat schema; assert
    is_alive returns True within max_age_seconds of a fresh write.
  - Exit: PF1 uptime > 0% in the deployment_decision.json output on box post-rebuild.

[1] SCP + rebuild box with D.1 + D.3 + [0]:
  - paramiko SCP (or scp + ssh mv -f) for each of:
      trading/live_paper_runner.py
      monitoring/metrics_exporter.py
      monitoring/heartbeat_monitor.py
      production_readiness/metrics_aggregator.py  (already on box from session 2; SCP only if changed by [0])
      state/__init__.py, state/schemas.py (new tree)
      risk/strategy_halt.py (new)
      trading/strategy_isolation.py (new)
  - docker compose -f deployment/docker-compose.yml up -d --build --no-deps aaats-paper-crypto
  - Verify: docker exec aaats-paper-crypto python scripts/evaluate_live_readiness.py
    — expect drawdown in [-30%, 0%] (state's actual), uptime > 0%, all 3 blockers
    showing real numbers (not arithmetic garbage).
  - Verify D.3 smoke: docker logs aaats-paper-crypto 2>&1 | grep state-smoke
    — expect 4 OK + 1 OK (risk_engine_state) lines on a healthy container.
  - Verify D.1: docker exec aaats-paper-crypto python -c "from risk.strategy_halt import list_halted_strategies; print(list_halted_strategies())"
    — expect [] (no halts).

[2] B.2 — C3 PARAM-TUNE + symbol-halt patch:
  - File: trading/altcoin_reversion.py
  - (a) Wire BTC_DOM_FAST_RISE filter into _entry_allowed (lines 314-330; constant
        at :77 currently unread). Pass btc_dom_delta from the caller in
        run_altcoin_reversion_crypto (line ~459-463) — the runner already has
        btc_dom at trading/live_paper_runner.py:1625.
  - (b) Extend symbol deny-list at trading/altcoin_reversion.py:487 (per-cycle
        universe loop) to include OP/USDT, ARB/USDT, PUMP/USDT, FET/USDT, LUNC/USDT.
        Justification: 0/8 SELL win rate on these 5 over 9 days; residual C3 P&L
        without them = -$1.216/9d (session 1 symbol-halt math).
  - Tests: tests/test_altcoin_reversion_btc_dom_filter.py — synthetic high-BTC.D-rise
    test asserts entry is refused; synthetic deny-listed-symbol test asserts skip.
  - Backtest: scripts/backtest_c3_param_sweep.py (if extant; otherwise run paper-shadow
    for 7d).
  - Exit: pre-patch realized P&L curve vs post-patch projection documented; tests
    green; SCP-deploy patch as a separate rebuild AFTER [1] has been verified.

[3] D.2 — Heartbeat watchdog (sidecar container):
  - See addendum §"Phase D.2" for full spec.
  - new health/watchdog.py + Dockerfile.watchdog + compose service `aaats-watchdog`.
  - Detect: now - heartbeat.timestamp > 3 * CYCLE_INTERVAL_SEC (= 3 * 900 = 2700s).
  - Recovery: docker restart aaats-paper-crypto, rate-limited to 3 in 30min.
  - Tests: manual kill of aaats-paper-crypto → watchdog detects, Telegram fires,
    container restarts; repeat 4x → 4th attempt skipped + escalation message.
  - This depends on [0] (the watchdog reads the FLAT heartbeat schema).

[4] A.1 — State isolation prep (read-only design):
  - Per-mode risk_engine_state files (risk_engine_state.paper.json vs
    risk_engine_state.live.json). Today's STATE_FILE at risk/engine.py:44-46 is a
    single path.
  - Write a design memo at docs/decisions/2026-05-22_state_isolation_design.md with
    the proposed env-var discriminator + named-volume implications. NO code edits.
  - Implementation deferred to session 4.

Constraints (unchanged from sessions 1+2, with one addition):
  - No SCP deploy from dirty tree.
  - **`git pull --rebase` BEFORE every push.** The Contabo box auto-pushes
    `data/`+`logs/` snapshots to origin/main every 15 minutes; a long session
    will see 30-60 of those commits land while you work. Rebase is conflict-free
    because the auto-cron only touches data/ + logs/, but a non-rebased push
    will be rejected. (Surfaced session 2; standing rule going forward.)
  - Push to GitHub at end of session.
  - No behavior change in trading/, execution/, risk/ paper paths without
    failing-then-passing test.
  - Keep paper-crypto running. Use `--no-deps aaats-paper-crypto` only.
  - PAPER_MODE env var stays unused (still A.1+ scope).

Reporting at session end:
  - Append to "Status log" in docs/decisions/2026-05-22_live_flip_rebuild_plan.md
    ([0]+[1]+[2] ship report + verify outputs).
  - Append to "Status log" in docs/decisions/2026-05-21_track_d_reliability_addendum.md
    ([0] heartbeat reader fix + [3] D.2 + [4] A.1 design memo links).
  - Overwrite docs/decisions/2026-05-21_next_session_prompt.md with session 4 prompt.
  - Commit + push.
  - Ping operator only on kill-switch events (drawdown more negative than -30%
    measured by state file, share-equality delta > $0.50, or container failing
    to start after rebuild). Otherwise no ping needed.

Start with [0] legacy heartbeat reader removal — small, cheap, unblocks PF1
uptime > 0%. Then [1] SCP + rebuild box. Then [2] + [3] + [4] are parallel-safe.

KNOWN SUB-AGENT QUIRK (still active 2026-05-22): spawned Agents (via the Agent
tool) may hit Write-tool permission denials on this workstation; main-context
Edit/Write work fine. If you delegate to subagents, instruct them to return
content in their reply, not call Write directly.
```
