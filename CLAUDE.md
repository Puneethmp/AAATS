# AAATS — Operator Notes for Claude Code

Deploy discipline rules: see docs/conventions/deploy_discipline.md (canonical).

## Deploy mechanism (paramiko SCP — NOT `git pull`)

The Contabo box (`aaats@100.95.126.39`, dir `/home/aaats/aaats`) is **not a git
repo**. Code is shipped from a Windows workstation via `paramiko` over SSH:

1. For each changed source file, upload to `<path>.tmp`, then `mv -f <path>.tmp <path>` (atomic swap on the box).
2. Rebuild the affected container without taking down siblings:
   ```bash
   docker compose -f deployment/docker-compose.yml up -d --build --no-deps aaats-paper-crypto
   ```
3. Bind mounts on `aaats-paper-crypto` are `scripts/`, `data/`, `logs/` — edits inside those paths are live without rebuild; anything else needs the rebuild step.
4. Record SHAs and rollback baselines in `.rollback/<date>_<change-id>/` (see `.rollback/2026-05-15_p0p1/MANIFEST.txt` for the template).

Deploy scripts refuse uncommitted manifest files; use `--allow-dirty` in genuine emergencies only and commit immediately after.

**Box auto-cron pushes to origin/main every 15 minutes** (surfaced 2026-05-22 session 2). A cron job on the Contabo box commits `data/` + `logs/` snapshots and pushes them. A typical Claude Code session will see 30–60 of these commits land on origin/main mid-session. Every push from the workstation must `git pull --rebase` first. Conflicts are not expected because the auto-cron only touches `data/` and `logs/` — workstation work touches `trading/`, `monitoring/`, `state/`, `risk/`, `docs/`, etc.

Compose layout: `aaats-paper-crypto` belongs to project `deployment` (config under `/home/aaats/aaats/deployment/`); Grafana/Prometheus belong to project `aaats-base` (config under `/srv/aaats/compose/`). A `compose down` from one path does not touch the other.

### Cron liveness — 4-layer monitoring (canonical 2026-05-24)

The auto-cron push stream is monitored by four independent layers. Full design: [docs/decisions/2026-05-24_auto_cron_resilience.md](docs/decisions/2026-05-24_auto_cron_resilience.md). Runbook: [docs/runbooks/auto_cron_recovery.md](docs/runbooks/auto_cron_recovery.md).

| Layer | Where it lives | What it catches | How to verify |
|---|---|---|---|
| L1 GitHub Actions liveness | `.github/workflows/liveness-monitor.yml` (runs on github.com infra) | origin/main has no auto-cron commit for >30 min — including full box outage | Actions tab → AAATS liveness monitor; gated by repo variable `LIVENESS_ENABLED=true` |
| L2 in-cron hardening | `/home/aaats/bin/aaats-autopush.sh` (v3 since 2026-05-24) + `/home/aaats/bin/aaats-cron-alert.sh` | Cron ticked but push failed; alert fires after 3x backoff retries | `cat /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json` — `status=ok` means last tick pushed |
| L3 heartbeat watchdog | `/home/aaats/bin/aaats-heartbeat-checker.sh` (crontab `*/5 * * * *`) | Heartbeat file >20 min stale — cron daemon dead or autopush hung | `tail /home/aaats/aaats-heartbeat-checker.log` |
| L4 diagnose.sh | `/home/aaats/bin/aaats-diagnose.sh [--quick]` | n/a — on-demand triage tool | `ssh aaats@100.95.126.39 'bash /home/aaats/bin/aaats-diagnose.sh --quick'` |

Source-of-truth for box scripts is `scripts/box/` in this repo. The heartbeat file (`/srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json`) is canonical for "did cron tick" — read it before assuming origin/main reflects current box state.

**Investigating a suspected outage:** ALWAYS `git fetch origin main` before reading `git log origin/main`. The local reflog is just a cache; a stale one made a 0-minute outage look like 15h on 2026-05-24 ([docs/known_issues/2026-05-24_cron_blackout_false_positive.md](docs/known_issues/2026-05-24_cron_blackout_false_positive.md)).

## Container has no `sqlite3` CLI

Use `docker exec aaats-paper-crypto python -c "import sqlite3; ..."` for ad-hoc queries.

## Observability — ports & exporters (canonical 2026-05-16)

| Service | Container | Port (host:container) | Notes |
| --- | --- | --- | --- |
| Prometheus exporter | `aaats-metrics` | `9091:9091` | Source: `monitoring/metrics_exporter.py:30`. Image `sha256:c9e2e54ab593…` (rebuilt 2026-05-16T06:21Z to persist `aaats` network attachment in compose; prior `79c80b570b95…` baked in `collect_share_equality()`). Scraped by Prometheus per `/srv/aaats/compose/prometheus/prometheus.yml`. Hosts the share-equality counter and all per-strategy gauges. |
| Trading container | `aaats-paper-crypto` | (none) | Image `sha256:1a06f1a3de03…` (rebuilt 2026-05-16 with full RUNTIME-LATENT tree + paper_trader.py drift fix). Exposes no ports; metrics surfaced by `aaats-metrics` reading shared `data/` bind mounts. |
| Grafana | `aaats-grafana` | Tailscale-only on `:3000` | See memory `project_aaats_grafana.md`. |

If a script or doc references `aaats-paper-crypto:8001`, it is stale — that
endpoint was retired when the exporter was split into the standalone
`aaats-metrics` container. Don't resurrect it without compose changes.

### Share-equality alert chain — operational

Validated end-to-end by synthetic WARN on **2026-05-16T04:39:00Z** (chain: exporter
9091 → Prometheus → Grafana rule `share_equality_mismatch` → Telegram chat
`1946109268`). Production trigger: `execution/paper_trader._bump_share_mismatch_counter`
writes `data/share_equality_mismatches.json` on every WARN; the exporter scrapes
that file on the 30s `SCRAPE_INTERVAL`. Synthetic test recipe: write
`{"_TEST_|_TEST_": <n>}` into that JSON twice (to give `increase()[1h]` a delta).

**Network attachment** (persistent as of commit `708b58b`, 2026-05-16): `aaats-metrics`
declares `networks: [default, aaats]` in `deployment/docker-compose.yml` and the
top-level `networks:` block lists `aaats: external: true`. This survives container
recreation. Do NOT run `docker network connect aaats aaats-metrics` manually —
compose owns this attachment now.

## Kill-switch semantics (verdict 2026-05-23)

The -15% per-market and -20% portfolio kill thresholds at [risk/engine.py:38-39](risk/engine.py#L38-L39) are **new-entry gates, not liquidation gates**. When `RiskEngine.update_market` observes drawdown ≤ -15%, it sets `_halted_markets[market]` (in-memory) and returns `HALT_MARKET` with `allowed_fraction=0.0`. The runner's `apply_kill_switch_gate` honors this by short-circuiting `execute()` and the C3/C6 standalone gates before any order is placed. **Open positions continue to mark-to-market.** A separate -2% per-trade stop ([risk/engine.py:340-368](risk/engine.py#L340-L368)) handles per-position liquidation; the market-level kill does NOT.

Three parallel halt channels exist and are intentionally **NOT synchronized**:

| Channel | File | Set by | Cleared by |
|---|---|---|---|
| Operator/CLI halt | `data/halt_state.json` | `kill.py` CLI / `foundation/kill_switch.halt()` | `foundation/kill_switch.reset()` |
| Engine market-DD halt | in-memory `RiskEngine._halted_markets` | `engine.update_market()` on DD ≤ -15% | re-derives every cycle from persisted peak |
| Strategy auto-halt | `data/strategy_halt_state.json` | `risk/strategy_halt.halt_strategy()` after 3 consec exceptions | `risk/strategy_halt.reset_strategy()` |

Reading `halt_state.json` is meaningful for the **operator** channel only. A `crypto: false` value does NOT mean the engine kill is off — the engine has its own per-process halt state that regenerates from the persisted peak on every cycle. Investigation memo: [docs/known_issues/2026-05-23_kill_trigger_investigation.md](docs/known_issues/2026-05-23_kill_trigger_investigation.md).

`run_crypto` now short-circuits at top-of-cycle on `is_halted("crypto")` (parity with `run_india`, added 2026-05-23 session 6). The runner-wide kill skip is on the **operator** channel; the per-order engine kill still gates each `execute()` independently.

## Where to find what (doc layout)

- **Invariants that never change across sessions** — this file (`CLAUDE.md`).
- **"Why" behind each locked architecture choice** — `docs/decisions/*.md`. Before re-litigating any settled decision (broker choice, ledger spec, doctrine, sizing), grep this folder first. The latest decision wins; the earlier ones are kept for history with a SUPERSEDED tag.
- **Rotating session scope (current sprint, exit criteria)** — `docs/sprints/*.md` and the active `docs/decisions/2026-05-21_next_session_prompt.md` (overwritten by each Claude Code session at end).
- **Active autonomy contract** — `docs/decisions/2026-05-21_autonomy_contract.md`. Claude reads at session start; operator revokes/narrows by writing "autonomy contract revoked" in any Cowork chat.
- **Known issues + bounded bugs** — `docs/known_issues/*.md`.
- **Technical specs (schemas, runbooks)** — `docs/specs/*.md`, `docs/runbooks/*.md`.

## Model tiering — match the task to the cheapest viable tier

The AAATS rebuild is ~80% implementation work, which is Sonnet-grade. Defaulting to Opus on every session burns the monthly plan limit and rarely helps. Use this map:

- **Opus** — broker abstraction design, risk-engine logic changes, ledger schema work, debugging non-obvious failures (memory leaks, race conditions, cross-container state corruption), Cowork architecture / strategy sessions where the question is "what should we do." Examples in AAATS: writing this doc; the 2026-05-21 NO-GO investigation; the unified-ledger Q1–Q4 design.
- **Sonnet** — implementation of a decided design, pandas/SQLite transforms, broker adapter coding, test writing, paramiko SCP scripts, documentation, retry/backoff plumbing, schema-drift assertions. The vast majority of Track A/B/D execution lands here.
- **Haiku** — log parsing, CSV cleanup, batch parameter-sweep result summarization (post-B.2), generating test fixtures, mechanical refactors. AAATS doesn't have much Haiku-grade work yet; will gain volume during B.2 sweeps.

If a Sonnet session stalls on a genuinely non-obvious bug, escalate to Opus for that one session. Don't pre-emptively start every session on Opus "to be safe" — it's the most common way to run out of capacity mid-sprint.

## Subagent usage

The Agent tool (Task tool) lets a session dispatch read-only research, planning, or exploration in parallel without burning the main context. For AAATS this is highest leverage during:

- B.0/B.0.5 strategy diagnostics (one Explore agent per strategy).
- D.0-style catalog passes that read every `docs/known_issues/*.md`.
- Cross-file consistency checks (Plan agent reviewing whether a schema change touches everything it should).

**Known quirk (2026-05-21):** spawned Agents hit Write-tool permission denials on this workstation. Main-context Edit/Write work fine. **Pattern:** when delegating to subagents, instruct them to *return content in their reply*. The parent context writes the files. Do not have the subagent call Write/Edit/NotebookEdit directly — it will fail silently or noisily depending on tool.

Parallelism rule: when independent agents are dispatched, send them in the SAME message (multiple Agent tool calls in one assistant turn). Serializing them defeats the purpose.
