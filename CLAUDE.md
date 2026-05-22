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
