# Track D — Reliability & self-healing (addendum to 2026-05-22 rebuild plan)

**Status:** ACTIVE — adds Track D to [`2026-05-22_live_flip_rebuild_plan.md`](2026-05-22_live_flip_rebuild_plan.md).
**Authored:** 2026-05-21
**Author scope:** Cowork chat (Opus). Implementation lands via Claude Code session — see [`2026-05-21_next_session_prompt.md`](2026-05-21_next_session_prompt.md).

## Why this addendum exists

The 2026-05-22 rebuild plan covers two failure modes: live-flip mechanism (Track A) and strategy P&L (Track B). It does **not** cover the operator-reported pain that has caused this project to restart for ~15 days:

> "I'm not able to complete the paper trading also for 2-4 weeks because some or the other way the system is breaking."

This is a **reliability** problem, distinct from correctness. The existing 27-component tree can be 100% mechanically correct and still fail the operator's lived experience if the container crashes, the loop wedges, or an unhandled exception silently halts the strategy stack mid-week. Track D closes that gap.

Track D is **parallel-safe with A and B** — it touches `monitoring/`, `deployment/docker-compose.yml`, and adds a `health/` module; none of these conflict with Track A's state-isolation work or Track B's strategy triage.

## The reliability failure modes — what actually breaks

Catalogued from `docs/known_issues/2026-05-15_*.md` and the 2026-05-21 NO-GO investigation:

1. **Silent halts** — `halt_state.json` flips a market to `true`; the loop keeps spinning but emits no trades. Operator only notices days later when checking PnL. See `2026-05-21_aaats_engine_v6_halt.md` (v6 engine sat in -15.5% halt undetected).
2. **Schema drift between writer and reader** — heartbeat written flat by `execution/live_paper_runner.py`, read nested by `monitoring/heartbeat_monitor.py` (NO-GO doc §"Display-only PF1 blockers"). No alert fires when the heartbeat goes stale.
3. **Container restart loses in-flight state** — `risk_engine_state.json` is volume-persisted so peak/drawdown survive, but the cycle counter, in-progress orders, and one-shot dust-filter init flags do not. Restart = subtle behavioural delta the operator has to debug.
4. **Exception in one strategy halts the cycle** — `paper_loop.py` has a single try/except around the cycle, not per-strategy. C5b's known halt cascades into "no strategy ran this cycle" rather than "C5b skipped, others ran."
5. **No watchdog on the metrics exporter** — if `aaats-metrics` drops off the `aaats` network (the bug fixed in commit `708b58b` on 2026-05-16), Prometheus scrapes return stale data for hours before anyone notices. The fix was reactive; the watchdog is still missing.
6. **No daily health digest** — operator has to actively `docker exec` + query SQLite to know whether the bot ran cleanly yesterday. Cognitive load + missed failures.

## Phases

### Phase D.0 — Failure-mode inventory & alert mapping

- **Scope:** read every `docs/known_issues/*.md` and `docs/decisions/*.md`. Produce a table: failure → detector (does one exist?) → alert (does one fire?) → recovery (manual or auto?). Output: `docs/specs/reliability_failure_modes.md`.
- **Why this is needed:** before adding self-healing, we need a single source of truth listing what can go wrong. Without it Track D becomes whack-a-mole.
- **Exit criteria:** table merged; gaps (failures with no detector OR no alert OR no auto-recovery) ranked by frequency from the operator's lived experience.
- **Estimate:** 1 session.
- **Dependencies:** none. Parallel-safe with A.0 and B.0.

### Phase D.1 — Per-strategy exception isolation

- **Scope:** wrap each strategy execution in its own try/except inside `paper_loop.py` (and the future `live_loop.py`). On exception: log with `strategy_id` and `cycle_id`, increment a Prometheus counter `strategy_exception_total{strategy="..."}`, continue the cycle. Three consecutive exceptions in the same strategy → auto-HALT that strategy only, write to `halt_state.json` with reason.
- **Files touched:** `trading/paper_loop.py`, `monitoring/metrics_exporter.py` (new counter), `risk/halt_state.py` (helper).
- **Tests required:** synthetic strategy that raises on cycle 3 — assert other strategies run on that cycle and after; assert auto-HALT triggers on cycle 5 (3rd consecutive exception); assert Telegram fires.
- **Exit criteria:** unit + integration tests green; manual smoke on box shows the synthetic strategy halted alone.
- **Estimate:** 1 session.
- **Dependencies:** D.0 (so we know what we're isolating against).

### Phase D.2 — Heartbeat watchdog + auto-restart

- **Scope:** new `health/watchdog.py` runs as a tiny sidecar container. It tails `data/heartbeat.json` (writer is `paper_loop.py`). Rule: if `now - heartbeat_ts > 3 × cycle_interval`, send Telegram CRITICAL with last 50 lines of the container log, then `docker restart aaats-paper-crypto`. Rate-limit auto-restarts: max 3 in 30 minutes, then escalate (Telegram-only, no further restart).
- **Files touched:** new `health/watchdog.py`, new `deployment/Dockerfile.watchdog`, `deployment/docker-compose.yml` (add `aaats-watchdog` service).
- **Tests required:** kill `aaats-paper-crypto` manually → watchdog detects within 3 cycles → Telegram fires → container restarts → heartbeat resumes. Loop the kill 4 times → watchdog stops restarting on the 4th, sends escalation.
- **Exit criteria:** end-to-end test on box: synthetic 5-minute stall → recovery completes within 90s of detection.
- **Estimate:** 1 session.
- **Dependencies:** D.0 (failure-mode catalog informs the rate-limit + escalation rules).

### Phase D.3 — Schema-drift assertions on startup

- **Scope:** every JSON state file that has a writer + reader pair (`heartbeat.json`, `halt_state.json`, `risk_engine_state.json`, `paper_positions.json`, `share_equality_mismatches.json`) gets a pydantic model in `state/schemas.py`. Writers validate before write; readers validate after read. Startup smoke runs all 5 reads and asserts. Mismatch = container refuses to start with a clear error, not silent corruption.
- **Files touched:** new `state/schemas.py`, all writer/reader sites (greppable from `_record`, `_save_state`, `load_state` patterns).
- **Tests required:** synthetic corrupted JSON → container fails fast with the field-level error. Round-trip test for each schema.
- **Exit criteria:** every JSON state file has a schema, writers and readers both use it, CI runs a "schema sweep" test.
- **Estimate:** 1–2 sessions (size depends on how many writer/reader pairs there really are — D.0 will pin this).
- **Dependencies:** D.0.

### Phase D.4 — Daily health digest to Telegram

- **Scope:** scheduled task fires at 09:00 IST daily (after IST market open). Computes from `paper_trades.db` + state files: yesterday's P&L (realized + unrealized), cycle count, uptime %, exceptions raised, restarts triggered, alerts fired, current peak/drawdown, top 3 firing strategies, top 3 silent strategies. Sends as a single Telegram message in fixed format. **Operator should be able to check Telegram once and know whether to look closer.**
- **Files touched:** new `monitoring/daily_digest.py`, new scheduled task in `mcp__scheduled-tasks__create_scheduled_task` (or cron inside the watchdog container — decision deferred to implementation).
- **Tests required:** golden-output test on a fixed snapshot of the DB + state files. Manual dry-run of the digest against today's box state.
- **Exit criteria:** digest fires once with all sections populated; format reviewed and locked in this doc as Appendix A.
- **Estimate:** 1 session.
- **Dependencies:** D.0 for the field list.

### Phase D.5 — 30-day soak

- **Scope:** the bot runs for **30 consecutive calendar days** without operator intervention. Defined intervention = anything beyond reading the daily digest. If anything requires manual `docker exec` or `ssh aaats@`, the 30-day clock resets.
- **Success metric:** 30/30 days delivered a digest, every digest closed cleanly (no unresolved alerts), no manual ops needed.
- **Exit criteria:** the metric above. This is the operator's actual definition of "the bot is independent."
- **Estimate:** 30 days calendar. Cannot be compressed.
- **Dependencies:** D.1 through D.4 complete.

## Dependency graph (Track D overlaid on existing plan)

```
Week 1: [A.0] -> [A.1]        [B.0] -> [B.0.5] -> [B.1]        [D.0] -> [D.1]
Week 2: [A.1] -> [A.2]        [B.1] -> [B.2]                   [D.2] -> [D.3]
Week 3: [A.2] -> [A.3] -> [A.4]   [B.2] -> [B.3 soak]          [D.4]
Week 4: [B.3 soak]                                              [D.5 soak begins]
Week 5-8: Track C gate evaluation when (A.4 green) AND (B.3 green 4 weeks) AND (D.5 green 30 days)
```

**Net impact on calendar:** D.5 soak overlaps B.3 soak, so the live-flip critical path is unchanged. Track D adds ~5 Claude Code sessions of implementation work, parallel-safe with A and B.

## Updated Track C gate (additive)

Track C from the parent plan stays as-is. Add:

- **C.6** — D.5 30-day soak passed: 30 consecutive daily digests delivered, zero unresolved alerts, zero manual ops. Cite: the 30 digest payloads archived in `data/digests/`.

## Appendix A — Daily digest format (LOCKED)

```
🤖 AAATS daily digest — YYYY-MM-DD (T+N since rebuild)

📊 P&L (24h)
  Realized:   $±X.XX
  Unrealized: $±X.XX
  Equity:     $XXX.XX  (peak $XXX.XX, dd −X.X%)

⚙️  Operational
  Cycles run:        N (expected N, X.X% uptime)
  Exceptions:        N  (Y auto-halted)
  Container restarts: N  (auto: A, manual: M)
  Alerts fired:      N  (open: X, resolved: Y)

📈 Strategies (24h)
  Firing:   Cn (X trades), Cm (Y trades), Co (Z trades)
  Silent:   Cp, Cq, Cr   (reason: ...)
  Halted:   Cs (since YYYY-MM-DD, reason)

⚠️  Action needed: NONE | <one-line summary>
```

The `Action needed` field is the operator's single decision-trigger. If it's `NONE` for 30 consecutive days → the bot is independent by D.5's definition.

## What this addendum does NOT do

- Touch strategy code (Track B owns that).
- Touch the live-flip mechanism (Track A owns that).
- Add new alerting infra (uses the existing Telegram + Prometheus + Grafana stack from CLAUDE.md).
- Re-litigate the locked doctrine — D.5 is **additive** to Track C, not a replacement.

## Status log (append-only)

- **2026-05-21 evening** — Track D drafted. Operator chose surgical stabilization + full technical autonomy in Cowork session. Implementation kickoff queued for next Claude Code session via [`2026-05-21_next_session_prompt.md`](2026-05-21_next_session_prompt.md).

- **2026-05-21 (session 1)** — **D.0 SHIPPED.** Failure-mode catalog
  merged at [`docs/specs/reliability_failure_modes.md`](../specs/reliability_failure_modes.md).
  23 rows ranked by operator-impact score (`silent_weight ×3 + recurrence_weight ×2 + recovery_cost_weight ×1`),
  citing 19 source documents. Severity legend (S1/S2/S3), ranking
  heuristic, and rebaseline procedure are all in-doc.

  **Top 3 highest-ranked modes:**
    1. Heartbeat goes stale undetected (writer flat / reader nested
       schema mismatch). Closes via D.2 + D.3.
    2. One strategy raises exception → entire cycle aborts (no
       per-strategy isolation). Closes via D.1.
    3. Container silently sits in `halt_state.json={crypto:true}` while
       loop spins emitting no trades (v6 pattern: -15.5% halt undetected
       for 3+ days). Closes via D.4.

  **Cross-cutting findings worth surfacing:**
    - 6 of the top 10 rows are S1 silent failures — the operator's lived
      pain ("system breaks every 2–4 weeks") is structurally a detection-gap
      problem, not a catastrophic-crash problem. D.2 + D.4 are
      correctly targeted.
    - Schema-drift / dual-source-of-truth is the most common root cause
      (~9 of 23 rows). D.3 (schema-drift assertions) is the highest-leverage
      D.x phase by row-coverage.
    - Docker `healthy` is a load-bearing lie — rows 3, 21, and implicitly
      2 all show "container healthy AND strategy halted". D.2 watchdog
      must hang off trade-loop heartbeat file, NOT Docker healthcheck.
      Spec already captures this; flagged here so it does not drift.
    - The "halt_on_critical=False" pattern recurs across 4 rows: real
      signal exists but is suppressed downstream to keep operator from
      being woken up. Cumulative effect is that "no alert fired" no
      longer means "nothing was wrong." D.4's daily digest forces the
      suppressed-but-real state into one readable surface daily.

  **GAP-marked modes (NOT closed by D.1–D.4):**
    - Row 7 (metrics-exporter target-down) — propose D.6.
    - Row 17 (loguru printf-format recurrence-prone) — propose D.6 lint hook.
    - Row 22 (dead-code SELL-share recompute resurrection risk) — propose
      D.6 entry-point deny-list + lint rule.
    - Rows 5, 14, 15, 16 are closed by Track A, not D.x.
    - Row 8 (C5b $25/leg asymmetry) closed by unified-ledger sprint.

  Candidate D.6 scope is small (≤1 session); could be bundled as a
  single phase at operator's option. Listed as proposal, NOT auto-added.

  **Next D-track step:** D.1 (per-strategy exception isolation) +
  D.3 (schema-drift assertions on startup). Both depend on D.0 catalog
  (now merged). D.2 (heartbeat watchdog) is parallel-safe with D.1/D.3.

- **2026-05-22 (session 2)** — **D.1 + D.3 SHIPPED.**

  **D.1 — Per-strategy exception isolation.** New helper module
  `trading/strategy_isolation.py::run_strategy_with_isolation` wraps
  each strategy call with: (a) skip if `risk/strategy_halt.is_strategy_halted`,
  (b) on exception increment `total_exceptions` and `consecutive_exceptions`
  counters in `data/strategy_exception_state.json` and log with
  `strategy_id`, (c) at `consecutive_exceptions >= 3` auto-halt via
  `risk/strategy_halt.halt_strategy` (writes `data/strategy_halt_state.json`)
  plus best-effort `observability.alerts.send_alert` Telegram, (d) on
  success reset the consecutive streak. The 5 strategy-dispatch call
  sites in `trading/live_paper_runner.py` (N1 stat-arb-india, C1
  stat-arb-crypto, C2 momentum, C3 altcoin reversion, C6 bollinger
  range) were converted from bare `try/except → log.error` to the
  isolation envelope. Prometheus counter
  `aaats_strategy_exception_total{strategy=...}` plus the gauges
  `aaats_strategy_consecutive_exceptions{...}` and
  `aaats_strategy_halted{...}` exposed by
  `monitoring/metrics_exporter.py::collect_strategy_exceptions` (added
  to the `_scrape_all` collector list). Tests at
  `tests/test_strategy_isolation.py` cover the 7 cases mandated by
  the session-2 prompt + edge cases.

  **D.3 — Schema-drift assertions on startup.** New `state/` package
  with pydantic v2 models in `state/schemas.py` for the 5 JSON state
  files:

  - `HeartbeatSchema` — FLAT shape (timestamp / cycle / market /
    cycle_duration_seconds) — matches the runner's actual writer at
    `trading/live_paper_runner.py:1873-1882`; the legacy nested-per-market
    shape used by `monitoring/heartbeat_monitor.HeartbeatMonitor` is
    explicitly rejected. This catches catalog row 1 (the heartbeat
    writer/reader drift bug) at startup. **The drift is real and active**
    — PF1's post-deploy `evaluate_live_readiness.py` run on 2026-05-22
    surfaced `Failed to read heartbeats: Heartbeat() argument after **
    must be a mapping, not str` at `monitoring/heartbeat_monitor.py:142`,
    which is the nested reader trying to consume the flat writer's
    output. The legacy reader code path needs removal next session (the
    runner writes the canonical flat shape directly; the legacy reader
    is on a dead code path but still hit by PF1).
  - `HaltStateSchema` — `{us, india, crypto}` bool, extra forbidden so
    a typo like `cyrpto` fails fast.
  - `RiskEngineStateSchema` — `peak / last_update_ts / last_equity /
    market_peaks{crypto,india,us}`. Note: lives behind the
    `deployment_state-crypto` named Docker volume at
    `/app/data/state/risk_engine_state.json`; host bind-mount path is
    empty (see plan doc §"Diagnostic appendix" 2026-05-22 update).
  - `PaperPositionsSchema` — `{india, crypto}` empty-per-market dicts
    accepted with extra forbidden; per-symbol position dicts also
    accepted (canonical shape, see writer-drift memo).
  - `ShareEqualityMismatchesSchema` — bare dict `[str, int]` keyed by
    `strategy|symbol` → counter. Empty `{}` (current box state) and
    populated forms both supported; missing `|` separator or negative
    counts fail fast.

  Validating I/O helpers `load_validated(path, schema)` and
  `save_validated(path, model)`. Startup smoke
  `validate_all_state_files(data_dir)` runs all 5 reads at runner
  `main()` entry and refuses to start (`SystemExit`) on any INVALID
  result. MISSING / MISSING_OPTIONAL are tolerated (the runner is the
  writer for several files and re-creates them on the first cycle).

  **Test coverage:** 31/31 new + regression tests pass:

  ```
  tests/test_state_schemas.py          16 passed (D.3)
  tests/test_strategy_isolation.py      7 passed (D.1)
  tests/test_dual_ledger_drift.py       2 passed (regression — A.0 input)
  tests/test_live_readiness_scorer.py   6 passed (regression — A.0)
  ```

  **Cross-cutting findings folded back into the catalog:**

  - Catalog row 1 (heartbeat writer/reader schema drift) — now caught
    on startup by `HeartbeatSchema`. The active production bug at
    `monitoring/heartbeat_monitor.py:142` remains as a separate cleanup
    item — the reader code path is dead but still invoked by PF1 / the
    readiness scorer. Track this as "D.1+D.3 catches the schema, the
    legacy nested-reader is on the next-session cleanup list" rather
    than as an open detector gap. **D.3 closes catalog row 1's detection
    gap; the legacy code-path removal closes the active bug.**
  - Catalog row 12 (engine-vs-state drawdown disagreement) is now bounded
    by `RiskEngineStateSchema` requiring `peak > 0` and `last_update_ts >
    0`. Engine-emit-vs-state-write disagreement is a separate (Track A)
    issue; D.3 catches the state-file half of the pathology.
  - Sub-task 1.b (share-equality alert chain) — alert chain is **intact**
    (validated by 2026-05-16 synthetic test). Production state is
    correctly empty (`{}`); session 1's TON/FET-counter finding was a
    transient workstation observation, not a production state. Memo at
    `docs/known_issues/2026-05-22_share_equality_alert_chain.md`. **No
    new D-track row added; catalog unchanged.**

  **Next D-track steps:**
   - **D.2 (heartbeat watchdog)** — uses the FLAT heartbeat schema D.3
     defined; sidecar container that tails `data/heartbeat.json`,
     auto-restarts the trading container on stale heartbeat, rate-limits
     to 3 restarts / 30 min. Parallel-safe with B.2.
   - **Heartbeat legacy reader removal** — `monitoring/heartbeat_monitor.py`
     `HeartbeatMonitor.get_heartbeat` / `get_all_heartbeats` /
     `is_alive` rewrite for the flat schema. Touches every caller of
     `is_alive(market, ...)`, including
     `production_readiness/metrics_aggregator.py:241-246` (A.0 fix
     site) — at that point the PF1 uptime check should start returning
     non-zero.
   - **D.4 (daily digest)** — depends on D.3 schemas so the digest can
     read state files without defensive `.get(..., default)` everywhere.
   - **D.5 (30-day soak)** — once D.2 + D.4 land.

- **2026-05-22 (session 3)** — Legacy heartbeat reader removed (closes
  catalog row 1 ACTIVE bug) + D.2 watchdog code shipped + A.1 design memo.

  **Heartbeat legacy reader removal — SHIPPED + box-deployed.**
  Closes the ACTIVE production bug `monitoring/heartbeat_monitor.py:142`
  flagged in session 2 ("argument after ** must be a mapping, not str").
  `monitoring/heartbeat_monitor.py` rewritten for the FLAT schema; the
  legacy nested-per-market `HeartbeatMonitor.emit_heartbeat` is gone.
  Dead callers of the old emitter cleaned (`trading/paper_loop.py::emit_cycle_heartbeat`
  had no real callers; deleted). Post-deploy PF1 verification ran clean:
  `Infrastructure Uptime` is **no longer in the blockers list** (was 0.0%
  the whole sprint; now reads non-zero per-market freshness). Tests at
  `tests/test_heartbeat_monitor.py` (11 cases) + the prod-shape fixture
  in `tests/test_state_schemas.py` (D.3 schema-drift assertion) form the
  combined guard.

  **D.2 — Heartbeat watchdog — CODE + TESTS shipped, box deploy deferred.**
  Per the §"Phase D.2" spec:
    - Detect: `now - heartbeat.timestamp > 3 × CYCLE_INTERVAL_SEC = 2700s`.
    - Recovery: `docker restart aaats-paper-crypto`, rate-limited to 3
      in 30 min; 4th detection escalates Telegram-only.
    - File: `health/watchdog.py` with a clean policy/IO split
      (`WatchdogState.classify` is pure logic; `Watchdog.tick` is the
      shell with file IO + docker CLI + Telegram via
      `observability.alerts.send_alert`).
    - Self-heartbeat at `data/watchdog_heartbeat.json` for
      meta-observability (catches the "watchdog is itself broken" case).
    - Sidecar: `deployment/Dockerfile.watchdog` (python:3.11-slim +
      docker CLI + python-telegram-bot only) + `aaats-watchdog` compose
      service mounting `/var/run/docker.sock` and `../data:ro`.
  Tests at `tests/test_watchdog.py` (11/11 green). Manual end-to-end
  smoke on box deferred to a follow-up rebuild (the docker.sock mount
  is operator-approval gated; queued for session 4).

  **A.1 — State isolation design memo — SHIPPED.**
  `docs/decisions/2026-05-22_state_isolation_design.md`. Read-only
  design; implementation queued for session 4 after operator review of
  the compose change (per-mode named volumes).

  **Cross-cutting findings folded back into the catalog:**
    - Catalog row 1 is now **CLOSED** at the code level: D.3 catches
      schema drift on startup, D.2 catches stale heartbeats at runtime,
      and the legacy nested reader (the producer of "argument after **
      must be a mapping, not str") has been removed. The drift class is
      structurally extinct, not just guarded against.
    - **New** finding: the production entry point is `trading/paper_loop.py`
      (a thin shim that delegates to `live_paper_runner.main()`), NOT
      `live_paper_runner.py` directly. Sessions 1+2's "runner main"
      references remain valid because the delegation path invokes the
      same `main()`, but the file-name label was the bug that surfaced
      this session as an unexpected `ImportError` on first rebuild.
    - **Box-side surprise**: `halt_on_critical=True` (set in session 2's
      `d1b7feb`) was not in effect on box until this session's deploy
      activated it. Post-deploy the reconciler HALTed every cycle on a
      pre-existing BTC/ETH ~$7 dust drift — restart-loop fingerprint.
      Operator approved reverting to `halt_on_critical=False` (band-aid)
      and deferring the BTC/ETH ledger drift root-cause to the
      unified-ledger sprint. This pattern (kill-trigger activates only
      when image rebuilds) is itself worth a catalog row — propose D.7
      ("kill-trigger config drift between workstation and box") at the
      operator's option; not auto-added.

  **Next D-track steps:**
   - **D.2 box deploy** — operator review of the docker.sock mount,
     then `docker compose up -d --build aaats-watchdog`. End-to-end
     test (kill `aaats-paper-crypto` → watchdog detects → Telegram
     fires → container restarts) per the §"Phase D.2" spec.
   - **D.4 (daily digest)** — depends on D.3 schemas (now landed +
     deployed). Implementation in a future session.
   - **BTC/ETH ledger drift root cause** — owned by the unified-ledger
     sprint, but the band-aid (`halt_on_critical=False`) is reversible
     in one line once the writer-side fix lands.
