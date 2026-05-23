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

- **2026-05-22 (session 4)** — D.2 box deploy + D.4 design memo. D-track
  status: D.0/D.1/D.2/D.3 all CODE+TESTS+BOX complete; D.4 designed,
  implementation queued; D.5 soak gate is now unblocked on the
  reliability side (the daily digest + watchdog visibility are the
  pre-requisites; D.5 starts the day digest fires cleanly).

  **D.2 watchdog — SHIPPED TO BOX.** Operator approved `/var/run/docker.sock`
  mount at session start. Deploy via `scripts/deploy_session4_d2_watchdog.py`.
  Image `sha256:4a27584eb76f...` running; smokes A-F all green
  (see [`2026-05-22_live_flip_rebuild_plan.md`](2026-05-22_live_flip_rebuild_plan.md)
  §"Status log" 2026-05-22 (session 4) [0] for the full smoke table).

  Two bug fixes shipped during deploy:
    - `Dockerfile.watchdog`: Debian 13's `docker.io` package excludes
      the CLI (in a separate `docker-cli` package). Switched to
      `docker-cli` (libc6 dep only, ~30 MB). Commit `89d601e`.
    - `docker-compose.yml`: data mount `:ro` → rw so the watchdog can
      write its own `data/watchdog_heartbeat.json`. The `:ro` was
      defense-in-depth nominal — the watchdog already has docker.sock
      write authority. Commit `b947573`.

  Deviated from prompt's `WATCHDOG_CYCLE_INTERVAL_SEC=10` smoke recipe
  — would runaway-restart paper-crypto whose actual cycle is 15 min.
  Safer protocol used: synthetic stale heartbeat in `/tmp` with
  monkey-patched restart/alert (smoke D) + one true socket-driven
  restart of paper-crypto via `docker exec watchdog docker restart`
  (smoke E). Real-box 4-restart escalation loop is unit-tested only;
  deferred to a maintenance-window follow-up.

  **D.4 daily digest design memo — SHIPPED.** Memo at
  [`2026-05-23_daily_digest_design.md`](2026-05-23_daily_digest_design.md).
  Format LOCKED per Appendix A above. Data sources mapped per field
  (paper_trades.db for P&L, state files for equity/exceptions/halts,
  docker inspect RestartCount for container restarts, NEW `cycle_log`
  table for canonical cycle attribution). **Dispatch decision:** inline
  in the aaats-watchdog poll loop — cleaner than cron / Task Scheduler /
  separate container; watchdog already paid the Telegram + data/ rw
  cost. Dry-run plan + Telegram destination (existing alerts chat) +
  Action-needed trigger matrix documented. Implementation is ~1 Sonnet
  session.

  **Cross-cutting findings:**
    - Smoke E (`docker restart` via socket) showed RestartCount did
      NOT increment. Docker's RestartCount only counts restart-policy
      triggered restarts (e.g., container exited unexpectedly), not
      explicit `docker restart`. The D.4 daily digest's
      "auto: A, manual: M" attribution will need to derive auto-count
      from `data/watchdog_heartbeat.json::restart_count_in_window`
      rather than `docker inspect RestartCount`. Folded into the D.4
      design memo.
    - The "Docker `healthy` is a load-bearing lie" cross-cutting
      finding from session 1 D.0 was reinforced: the watchdog's
      `_emit_self_heartbeat` silently swallows file-write errors,
      meaning a misconfigured mount produced a "running" container
      with zero self-observability for ~75s during smoke F. The
      session-4 deploy script now CHECKS for the self-heartbeat write
      as a hard exit code — but the underlying pattern (silent OSError
      swallow) is repeated across the codebase. Propose D.6: lint
      rule that flags `except OSError: pass` and `except Exception:
      pass` patterns in writer paths.

  **Next D-track steps:**
   - **D.4 implementation** — module + golden-output test + watchdog
     loop wiring + `cycle_log` table. ~1 Sonnet session.
   - **D.5 soak begin** — first day the digest fires cleanly with
     `Action needed: NONE`.
   - **D.6 (proposed)** — silent-except lint rule + the row-7/17/22
     items from session-1 D.0 catalog. Operator-optional bundle.

- **2026-05-23 (session 5)** — **D.4 SHIPPED + first live send confirmed.**

  **Module `monitoring/daily_digest.py`.** Pure builder
  (`build_digest(cfg, as_of, container_restart_count)`) + IO shell
  (`build_and_send_digest(...)`) + CLI (`python -m monitoring.daily_digest
  --dry-run [--as-of ...] [--data-dir ...]`). Sections per the locked
  Appendix A: P&L (24h realized from `paper_trades.db SELL.pnl`, unrealized
  from net open BUY notional minus matching SELL, equity + peak + dd from
  the A.1 per-mode `risk_engine_state.paper.json` with legacy fallback),
  Operational (cycles_run from the new `cycle_log` table, exceptions from
  D.1's `strategy_exception_state.json`, container restarts from `docker
  inspect` minus `watchdog_heartbeat.restart_count_in_window` for auto/
  manual split — per the session-4 cross-cutting finding), Strategies
  (firing/silent/halted via `paper_trades.db` + D.1 halt state), Action
  needed (NONE unless dd<=-10%, consecutive exceptions>=2, manual
  restart, or share-equality counter non-zero).

  **cycle_log table.** Idempotent CREATE TABLE IF NOT EXISTS +
  INSERT at `trading/live_paper_runner.py:1911-1934`, next to the
  heartbeat write. Same defensive try/except as the heartbeat path —
  a cycle_log write failure never breaks the trade loop.

  **Dispatch.** `health/watchdog.py::_maybe_dispatch_digest` fires once
  per IST calendar day at >= 09:00 IST (configurable via
  `WATCHDOG_DIGEST_HOUR_IST`, defaults to 9). Guard via
  `data/digest_log.json` so the 60-second poll only sends once.
  `WATCHDOG_DIGEST_DISABLED=1` short-circuits the dispatch for dry
  rollouts. Self-heartbeat now also records `last_digest_sent_for`.

  **Tests.** `tests/test_daily_digest.py` — 9/9 green:
    - golden-output (deterministic-input fixture, exact-string assertions
      on every section)
    - missing-state tolerance (cycle_log absent -> N/A; risk_engine state
      absent -> N/A; share_eq absent -> no trigger)
    - Action-needed trigger matrix (each of dd / consec exceptions /
      manual restart / share-equality individually fires; NONE when clean)
    - send-guard via digest_log.json + digests/ archive presence

  **Deploy.** `scripts/deploy_session5_d4_daily_digest.py` ships
  `monitoring/daily_digest.py` + the runner cycle_log writer + the
  watchdog dispatch wiring; rebuilds aaats-paper-crypto and aaats-watchdog;
  runs box dry-run smoke; verifies the cycle_log table exists post-cycle.

  **Two field-discovered issues fixed mid-deploy:**
    - `Dockerfile.watchdog` did not `COPY monitoring/` (the new module
      lives outside the previously-baked `health/` + `observability/`).
      Added the COPY; rebuilt watchdog. Image
      `sha256:e948bedc5171...`.
    - The first live digest fired correctly via the dispatch loop but
      reported `Action needed: NONE` against the known -33% paper
      drawdown because the watchdog container could not see
      `/app/data/state-paper/risk_engine_state.paper.json` — the A.1
      per-mode named volume was only mounted in paper-crypto. Compose
      patched to add `state-crypto-paper:/app/data/state-paper:ro` to
      the aaats-watchdog volumes. Today's `digest_log.json` entry
      cleared on the box; the watchdog's next 60s tick re-fired the
      corrected digest. Operator now has both messages in Telegram;
      the second (sent_at_utc 05:48:13Z) supersedes the first and
      correctly reports
      `Equity: $87.45 (peak $131.32, dd -33.4%) ... Action needed:
      drawdown -33.4% near kill threshold (-15%)`.

  Rollback baseline at `.rollback/2026-05-23_session5_d4_daily_digest/MANIFEST.txt`.

  **Cross-cutting findings:**
    - D.4's data sources implicitly depend on A.1's per-mode state path.
      A.1 box deploy and D.4 implementation landed the same session;
      had they been split, the watchdog's volume-mount gap would have
      been a between-session blocker. Sequencing was correct because
      A.1 came first (the digest is read-only on the file A.1 writes).
    - "Container has correct image AND correct file SHA AND correct
      service mounts AND can render the digest" all-true does NOT imply
      "the digest's reads return non-N/A". The state-paper mount is a
      DIFFERENT correctness boundary from the image-bake and the SHA
      checks. Going forward, the deploy smoke must explicitly verify the
      digest sees non-N/A equity, not just that the dry-run renders.
    - Telegram swallow-and-continue + send_alert no-op-without-creds
      meant the misleading first digest had no internal error. The
      digest's own correctness regression (Action needed wrongly =NONE
      against a known -33% dd) was caught only because the operator
      had the actual paper state in mind. A drift assertion ("digest
      claims dd=N/A while risk_engine reports dd!=N/A") could catch
      this at build time; deferred.

  **D.5 day-1 — infrastructure live, clock not yet started.**
  `data/digests/2026-05-23.txt` archive file written on the box (the
  corrected digest body). `digest_log.json` records the send with
  `ist_date=2026-05-23, sent=true`. D.5 day-1 begins on the first day
  the digest fires with `Action needed: NONE`, which is gated on B.3
  soak bringing the drawdown above -10%.

  **Next D-track steps:**
   - **D.5 day-1 begin** — gated on first NONE digest (B.3-dependent).
   - **D.6 (proposed)** — still queued (silent-except lint + the
     row-7/17/22 catalog items).
   - **Alerts log writer** — the digest's Action-needed "Alerts fired"
     row is currently N/A pending an `observability.alerts.send_alert`
     wrapper that appends to `data/alerts_log.json`. ~1 Haiku session.
   - **Drift assertion at deploy smoke** — the volume-mount-gap detector
     mentioned above. ~1 Haiku session.

- **2026-05-23 (session 6)** — **Alerts-log writer + D.6 lint + drift
  smoke + row 7/22 — ALL SHIPPED to workstation.**

  **Alerts-log writer.** `observability/alerts.py::send_alert` is now
  side-effecting: every call appends a JSON row to `data/alerts_log.json`
  (atomic .tmp+replace, severity inferred from message body unless
  explicit kwarg, UUID4 correlation_id auto-generated and returned to
  caller). `monitoring/daily_digest.py` reads the file, computes
  fired/open/resolved over the 24h window, switches `alerts_known=True`
  when populated, and adds a new Action-needed trigger:
  `alerts_open >= 3` fires the action line. Tests at
  `tests/test_alerts_log.py` (11/11 green) cover atomic-write,
  corrupt-file recovery, severity inference, explicit-vs-auto
  correlation_id, OSError-mid-replace robustness, and that
  KeyboardInterrupt propagates cleanly through to the loop. Digest
  tests in `tests/test_daily_digest.py` cover window-filter,
  resolution-pair, and the >=3-open trigger.

  **Drift assertion at deploy smoke.** `tools/operator/_digest_smoke.py`
  is the helper: takes a paramiko-like command runner (or a stub),
  probes the in-container state file with `test -s`, runs
  `python -m monitoring.daily_digest --dry-run` in the target
  container, and parses the Equity line. Returns ok/not-ok plus a
  diagnostic message. Tests at
  `tests/test_operator/test_digest_smoke.py` (9/9 green) cover the
  five scenarios: state-missing pass, state-present + good digest
  pass, state-present + N/A digest fail (the session-5 bug),
  non-zero digest exit fail, render-format-drift fail, plus the
  live-mode path variant. Next deploy script can wire this in via:
  ```python
  from tools.operator._digest_smoke import assert_digest_renders_equity
  ok, msg = assert_digest_renders_equity(ssh_runner, mode="paper")
  if not ok: sys.exit(f"deploy-smoke failed: {msg}")
  ```

  **D.6 lint sweep.** `tools/lint/silent_except.py` is an AST walker
  flagging two patterns: silent-except (`except <T>: pass`) and
  loguru-printf (`log.info("%s", x)` instead of `{}`). Repo baseline
  recorded at `tools/lint/silent_except_baseline.txt`: 80
  silent-except, 188 loguru-printf (after `# noqa: silent-except`
  annotations on the doctrine-correct paths in
  `foundation/kill_switch.py` and `observability/alerts.py`).
  `tests/test_lint_silent_except.py` is the ratchet CI gate — fails
  if either count rises; encourages downgrades. `tests/test_lint_logic.py`
  (10/10) tests the AST checks on synthetic fixtures. Future sessions
  can chip away at the 268 remaining hits.

  **Row 7 (metrics-exporter target-down):**
  `monitoring/metrics_exporter.py` gains `collect_self_up()` emitting
  `aaats_metrics_exporter_up=1` from inside the scrape loop. Distinct
  from Prometheus's `up{job="aaats-metrics"}` — the in-band gauge
  signals that the scrape loop has refreshed at least once (catches
  the deadlocked-loop-with-stale-cache failure mode the
  Prometheus-side `up` would miss).

  **Row 22 (dead-code SELL-share recompute resurrection):**
  `tests/test_dead_code_guard.py` asserts (a) the deleted
  `execution/{crypto,india}_runner.py` files have not reappeared,
  (b) no .py file outside the allowlist introduces
  `round(size_usd / entry_price, 6)`. 2/2 green.

  **NOT shipped to box this session.** All artifacts are workstation-only
  pending session 7's rolled-up deploy. The watchdog already has
  `monitoring/` baked into its image (session-5 fix); the alerts-log
  writer needs `observability/alerts.py` redeployed to paper-crypto
  for the alerts to begin populating.

  **Deferred to session 7+:**
    - C1 standalone kill-gate wire (`trading/stat_arb.py:478`) — B.2
      may force this if C1's z gate fires while crypto is in HALT.
    - D.5 day-1 begin — still gated on first NONE digest.
    - 268-hit lint cleanup — chip away gradually; each cleanup
      ratchets the baseline down.
    - C5b funding_arb re-enable — blocked on unified ledger Q1-Q4.

- **2026-05-24 (session 7)** — **Session-6 box deploy + D.6 chip-away
  + Row 7 verified live on box + C1 kill-gate wired.**

  **Bundled box deploy.** `scripts/deploy_session7_kill_alerts_lint.py`
  pushed alerts-log writer (`observability/alerts.py`), digest band
  wording (`monitoring/daily_digest.py`), the run_crypto operator-kill
  gate (`trading/live_paper_runner.py`), row 7 self-up gauge
  (`monitoring/metrics_exporter.py`), and the workstation helpers
  (`tools/operator/_digest_smoke.py`, `tools/lint/*`) in one atomic
  pass. Rebuilt `aaats-paper-crypto` + `aaats-metrics` + `aaats-watchdog`
  with `--no-deps`. Post-deploy SHAs at
  `.rollback/2026-05-24_session7_kill_alerts_lint/MANIFEST.txt`.

  **Smoke gates (all green):**
    - **Digest** — `docker exec aaats-watchdog python -m monitoring.daily_digest
      --dry-run` renders `Equity: $87.45 (peak $131.32, dd -33.4%)` and
      the new band wording fires correctly:
      `Action needed: drawdown -33.4% past portfolio-kill threshold (-20%);
      all new entries blocked, open positions continue to mark-to-market`.
      The session-5 N/A regression is no longer reachable.
    - **Row 7 (metrics-exporter self-up)** — `curl :9091/metrics` on
      the box returns `aaats_metrics_exporter_up 1.000000`. In-band
      liveness gauge complements Prometheus's `up{job="aaats-metrics"}`
      and surfaces the deadlocked-scrape-loop failure mode that
      Prometheus's target gauge would miss.
    - **Alerts log** — `data/alerts_log.json` is absent at deploy time
      (lazy creation on first `send_alert`). Digest currently reports
      `Alerts fired: N/A (alerts_log not yet populated)`; will switch
      to fired/open counts on the first HALT or strategy-exception
      alert post-deploy.
    - **Deploy-smoke helper** — `tools/operator/_digest_smoke.py` was
      wired into the deploy script via
      `assert_digest_renders_equity(_box_run, target_container=
      "aaats-watchdog", mode="paper")`; returned
      `ok=True message="digest renders equity correctly:
      $87.45  (peak $131.32, dd -33.4%)"`. The N/A drift assertion
      from session 6 is now part of every box deploy.

  **Surfaced finding — operator halt was being silently ignored
  pre-deploy.** `data/halt_state.json` on the box was
  `{us:true, india:true, crypto:true}` (set 2026-05-22 17:41 UTC,
  ~13 hours pre-deploy). Pre-deploy `run_crypto` ignored the operator
  channel entirely and traded freely. Post-deploy the session-6
  `is_halted("crypto")` gate fires correctly and the runner short-
  circuits. Operator chose to keep crypto halted (-33% drawdown
  justifies it). See live_flip_rebuild_plan.md session-7 entry for
  the full operator interaction.

  **Semantic gap surfaced (session 8 item).** The runner-wide
  short-circuit at top of `run_crypto` also stops MTM and exit code
  for open positions. The engine-level kill's documented semantics
  are "block new entries, keep MTM". Resolution options:
  (a) move the runner short-circuit BELOW the MTM/exit code so open
  positions continue to bleed, (b) accept current behavior as
  intentional and document it. Not addressed this session.

  **D.6 chip-away.** Top-leverage targets cleaned per session-6
  prompt:
    - `execution/paper_executor.py` lines 126/144/150/217/268/276/294 —
      f-string conversion (Row 17 motivation; fires on every trade).
    - `execution/idempotency.py` lines 179/191/200 —
      `sqlite3.OperationalError` silent-except handlers gained
      `log.debug(...)` bodies recording the exception text (column-
      exists / index-exists are the expected paths; unexpected
      variants now surface in forensic traces). New module-level
      `log = logging.getLogger(__name__)`.
    - My own session-7 stat_arb edits also converted to f-strings
      to avoid adding hits. Net delta: silent-except 80 → 77,
      loguru-printf 188 → 181 (-10 / -3). Baseline ratcheted at
      `tools/lint/silent_except_baseline.txt`; ratchet CI gate green.

  **Observation for future cleanup sessions.** The `loguru-printf`
  rule is conservative — it flags any `log.X("...%s...", arg)` call
  regardless of whether `log` is loguru or stdlib `logging`. Many
  flagged sites in `execution/`, `markets/`, `trading/` are stdlib
  logging where `%s` is correct. Two safe escape hatches:
  f-string conversion (works for both, but eagerly formats), or
  `# noqa: loguru-printf` annotation when the file is provably stdlib.
  A future D.6 refinement could detect the imported logger type and
  scope the rule to loguru-only modules, removing false-positive
  noise from the chip-away queue.

  **C1 standalone kill-gate — SHIPPED (prereq for B.2).**
  `trading/stat_arb.py` `run_stat_arb_crypto` + `_run_pair` now
  accept `full_positions` / `full_portfolio` kwargs and resolve
  `apply_kill_switch_gate` once per cycle, parity with C3 / C6.
  Gate is consulted before BUY emission at the entry block and
  before SELL emission at CONVERGE / HARD_STOP / TIME_STOP exit
  paths. Tests at `tests/test_stat_arb_kill_gate.py` (4/4 green).
  This closes the session-6 latent risk ("C1 would happily open new
  positions IF the entry-z fires").

  **Next D-track steps:**
    - D.5 day-1 begin — still parked at -33.4% drawdown; gated on
      first NONE digest (requires B.3 soak + recovery above -10%).
    - D.6 chip-away ongoing — 258 remaining hits (77 silent-except,
      181 loguru-printf). Each session can ratchet downward.
    - Lint rule refinement — scope `loguru-printf` to loguru-imported
      modules only, removing false positives. ~1 Haiku session.
    - Runner-halt-stops-MTM semantic review (item from session 7
      surfaced finding).

- **2026-05-23 (session 8)** — Operator-halt MTM gap closed +
  alerts-log smoke confirmed + D.6 chip-away (-6 silent-except).

  **Operator-halt MTM gap — SHIPPED.** This was the open semantic-gap
  item from session 7. Adopted option (a) per the session-8 prompt:
  the operator-halt channel now blocks new entries without freezing
  open positions. Implementation in
  [trading/live_paper_runner.py](trading/live_paper_runner.py):
    - Per-emission entry gate `apply_kill_switch_gate` consults
      `foundation.kill_switch.is_halted(market)` and the engine's
      HALT_ALL / HALT_MARKET decision. Blocks BUY emissions.
    - New `apply_kill_switch_exit_gate` only blocks on catastrophic
      engine HALT_ALL. HALT_MARKET and operator halt allow exits.
      Used by `execute()` SELL branch + C3 / C6 SELL paths + C1
      `_run_pair`'s `_exit_gate_ok` helper.
    - `run_crypto` + `run_india` no longer short-circuit on
      `is_halted`. They log the halt once and continue —
      `_check_trailing_stops`, MTM, exit signals all reachable.
    - Latent bug fixed along the way: the underlying
      `_mark_to_market_and_decide` helper now returns the more severe
      of `update_portfolio`'s and `update_market`'s decisions (HALT_ALL
      > HALT_MARKET > ALLOW). Pre-fix, a fresh engine that hit
      HALT_ALL via `update_portfolio` would still return ALLOW from
      `update_market` because the market peak was freshly seeded.

  Coverage: 12 new tests in
  [tests/test_operator_halt_mtm_gap.py](tests/test_operator_halt_mtm_gap.py)
  + 1 updated `tests/test_kill_trigger_paths.py` test that flips its
  assertion from "short-circuits when halted" to "reaches the Binance
  probe even when halted." Session-7 C1 kill-gate suite still 4/4
  green; in-scope repo test sweep 710/710 pass.

  **D.6 chip-away (lint).** Six more silent-except hits closed:
    - `execution/paper_trader.py:94, 106, 111` — sqlite3
      `OperationalError` migration handlers now `log.debug` the
      exception. Same pattern session-7 applied to `idempotency.py`.
    - `execution/status_db.py:50` — same pattern for the
      `engine_status` migration loop. Required adding a module-level
      logger; the module had none.
    - `foundation/mode_manager.py:128` — LIVE-activation Telegram
      alert failure now `log.warning`s rather than passing silently.
      Caveat embedded: mode switch still committed, alert is
      best-effort.
    - `diagnostics/d2_ml_dist.py:116` — per-bar `score_signal`
      exception now `print`s symbol + bar index instead of silently
      dropping the row.
  Net: `silent-except` 77 → 71 (-6). `loguru-printf` unchanged at 181.
  Baseline ratcheted.

  **Alerts-log smoke (session-7 deferred verification) — GREEN.**
  Synthetic `send_alert('TEST session 8 smoke 2026-05-23', market='crypto')`
  inside `aaats-paper-crypto` created
  `/home/aaats/aaats/data/alerts_log.json` (188 bytes, one row). Lazy
  creation contract holds; daily digest "Alerts fired" row will
  populate naturally on next watchdog tick after a real alert lands.

  **Loguru-only rule scoping — DEFERRED.** Chip-away has been
  progressing fine without the rule narrowing; save the Haiku session
  for when the queue runs lean.

  **Next D-track steps:**
    - D.5 day-1 begin — still parked, same conditions as session 7.
    - D.6 chip-away ongoing — 252 remaining hits (71 silent-except,
      181 loguru-printf).
    - Loguru-rule refinement still queued for a Haiku session.
    - Runner-halt-stops-MTM semantic gap — CLOSED this session.

- **2026-05-23 (session 9)** — Session-8 code shipped to box +
  state_bridge hotfix; D-track items DEFERRED to session 10.

  D-track had no scheduled item in session 9 (queue was [0] box deploy,
  [0b] state probe, [1] B.1.5 backtest, [3] PF5 only if time, [5] lint
  filler only). Session-9 time was consumed by deploy + hotfix + 60d
  backtest, leaving no slack for D-track chip-away. Status quo:

  - **D.5 day-1** — Still PARKED. Conditions unchanged: crypto under
    operator halt + drawdown -33.4%. Day-1 clock starts only after
    halt clears AND drawdown improves above the session-7 band wording
    threshold. Session 11 reset will clear both gates in one step
    (volume reinit at $200 floor → drawdown reset to 0, halt cleared).
  - **D.6 chip-away** — silent-except still at 71; loguru-printf still
    at 181. No work this session.
  - **D.1 auto-halt isolation (PF5.6)** — DEFERRED. Spec unchanged;
    session 10 picks it up as the lowest-blast-radius PF5 starter
    (pure monkeypatch).
  - **Loguru-only scoping** — still DEFERRED.

  **State-bridge gap (cross-cutting Track D finding).** Session-9
  deploy revealed that `foundation/state_bridge.py` and
  `foundation/positions.py` (committed 2026-05-21 in 464bf7e, behind
  `USE_UNIFIED_LEDGER` flag) had never been SCP'd to the box. The
  strategy modules shipped this session import them at top-level, so
  the box hit `ImportError` on every crypto cycle until the hotfix
  landed. Reliability implication: the deploy-discipline doctrine
  (`docs/conventions/deploy_discipline.md`) should be augmented with
  an "import graph" check that walks the shipped manifest's local
  imports and asserts every reachable local module is either in-manifest
  or already on the box. Filing this as a session-10 D-track candidate
  (low blast radius, augments existing
  `tools/operator/_dirty_tree_guard.py`).

  **Backtest harness as a Track D reliability tool.** The new
  `tools/backtest/` package is technically a Track B (B.1.5)
  deliverable, but it is now a permanent fixture that future Track D
  reliability work can lean on: any candidate strategy gate-tweak can
  be A/B'd on 60d of historical data before paper deployment. Worth
  noting in the D-track inventory.

  **Operator pings this session:** the B.1.5 PARTIAL recommendation
  (see `live_flip_rebuild_plan.md` status log session 9 for the full
  ping body). No D-track-specific ping required.
