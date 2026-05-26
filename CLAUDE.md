# AAATS — Operator Notes for Claude Code

Deploy discipline rules: see docs/conventions/deploy_discipline.md (canonical).

## Deploy machinery gotchas (canonical 2026-05-26)

Every deploy script must import `tools/operator/deploy_lib.py` and call its helpers instead of reinventing. The 9 recurring failure modes catalogued from the 2026-05-26 structural-fix deploy each have a one-line fix in that library:

1. **CRLF in `.sh`/`.py`/`.yml`/`.json`/`.md` on box** — paramiko SFTP and tarfile both preserve Windows CRLF. Box bash chokes on `\r`. Use `atomic_upload_normalized(sftp, local, remote)` instead of `sftp.put()`. For tarball-based deploys, normalize via `normalize_bytes_for_text_file()` before `tar.addfile()`. Bit twice in the 2026-05-26 session.
2. **Windows cp1252 console crashes on Unicode `→`** — call `enforce_utf8_console()` at the top of every deploy script.
3. **Box auto-cron 15-min race during push** — always use `auto_rebase_or_stash("main")` before any `git push` from the workstation. Documented since 2026-05-22 but kept biting because every script wrote its own ad-hoc version.
4. **Cowork-left stale `.git/index.lock`** — Cowork sandbox cannot `unlink` on the mounted filesystem. Every Windows-side deploy must `clear_stale_git_locks(repo_root)` first.
5. **Pre-commit ruff auto-reformat racing commit** — run `preflight_ruff_format(changed_files)` BEFORE `git add`. The pre-commit hook then sees clean files and the commit lands on first try.
6. **Grafana dashboard mount path drift** — running Grafana is in the `aaats-base` compose project (config under `/srv/aaats/compose/`), NOT the `deployment/` project. Repo dashboards live at `deployment/grafana/dashboards/` but the LIVE mount is `/srv/aaats/compose/grafana/dashboards/` (constant `GRAFANA_HOST_MOUNT`). Use `push_grafana_dashboard(sftp, client, local)` to land both copies. Bit during 2026-05-26 deploy — manually copied to recover.
7. **Box-side `.github/workflows/` dir absent** — box isn't a git repo; GitHub Actions reads from origin/main, not from the box. Remove `.github/*` from any deploy file list. Earlier scripts blindly uploaded these, requiring `mkdir -p` triage.
8. **Soft-fail `docker cp` noise** — `aaats-autopush-v3.sh` cp_state function now existence-guards via `docker exec ... test -f` BEFORE cp. Missing optional state files (`funding_arb_state.json` while C5b disabled, `share_equality_mismatches.json` before any WARN) skip silently. Set `EPHEMERAL_STATE_FILES` in `deploy_lib.py` lists which ones are guard-OK.
9. **paramiko binary mode preserves CRLF** — covered by #1 above; mentioned separately because the failure mode appears in tarball-based deploys too, not just per-file SFTP.
10. **Grafana datasource UID is `aaats-prom`, not `prometheus`** — the provisioned datasource at `/srv/aaats/compose/grafana/provisioning/datasources/prometheus.yml` declares `uid: aaats-prom`. Dashboard JSON files that hard-code `"uid": "prometheus"` (the default Grafana datasource UID in many templates) render "No data" on every panel because the UID doesn't resolve. Use `grafana_datasource_ref()` from `deploy_lib.py` in any dashboard JSON generator — the UID is then right by construction. Bit on 2026-05-26 v3 dashboard rollout (143 panel-level refs all wrong); fixed in-place via sed `s/"uid": "prometheus"/"uid": "aaats-prom"/g`.

Two follow-up gotchas not yet automated (manual operator action required, watching for recurrence):
- **Grafana admin API auth rejected** — `/srv/aaats/secrets/grafana_admin_password` is out of sync with the running Grafana's password. Pre-existing as of 2026-05-26; rotate when convenient.
- **`tools/operator/deploy_to_contabo.py` still uses raw tarball** — the older general-purpose deploy script hasn't been retrofit to use `deploy_lib`. Sprint follow-up.

Source: `docs/decisions/2026-05-26_deploy_hygiene_fix.md`.

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

**What auto-cron actually commits** (corrected 2026-05-24 during L7 build): only `runtime/`. The autopush snapshots `paper_trades.db`, `paper_positions.json`, `paper_portfolio.json`, `stat_arb_state.json` from the `aaats-paper-crypto` container into `/srv/aaats/runtime_repo/runtime/` then `git add runtime/` + commit + push. The earlier "commits data/+logs/" claim was aspirational; the actual scope is `runtime/` only. The `aaats-paper-crypto` source was previously wrong (was wired to `aaats-engine`, stale since 2026-05-06) — fixed in commit-set below. Per-strategy state files in `data/` are NOT auto-cron'd; they live in the host bind mount and are accessible to containers but not visible in origin/main.

**Investigating a suspected outage:** ALWAYS `git fetch origin main` before reading `git log origin/main`. The local reflog is just a cache; a stale one made a 0-minute outage look like 15h on 2026-05-24 ([docs/known_issues/2026-05-24_cron_blackout_false_positive.md](docs/known_issues/2026-05-24_cron_blackout_false_positive.md)).

### Content correctness — 6-layer monitoring (canonical 2026-05-24)

Cron-resilience (L1–L4) only catches "did the box push." Content-correctness layers catch "the bot looks alive but is silently miscounting / not trading / bleeding." Shipped 2026-05-24 in the pre-departure content-correctness sprint.

| Layer | Where it lives | What it catches | How to verify |
|---|---|---|---|
| L5 ledger divergence detector | `execution/paper_trader.py:compute_ledger_divergence` / `assert_ledger_consistency_or_halt` (called at top of `run_crypto`) | Per-strategy state-file open notional ≠ trade-DB-derived open notional by >$1 — halts the offending strategy via `risk/strategy_halt` and writes `data/ledger_divergence_alerts.json` | `docker exec aaats-paper-crypto python -c 'from execution.paper_trader import compute_ledger_divergence; print(compute_ledger_divergence())'` (empty dict = OK). Exporter: `aaats_ledger_divergence_usd{strategy=…}`. Pair strategies (C1/C5b) are passed through — see [`docs/known_issues/2026-05-24_l6_reconciler_posture_during_soak.md`](docs/known_issues/2026-05-24_l6_reconciler_posture_during_soak.md). |
| L6 reconciler posture (no code) | `scripts/reconcile_intracycle.py` (Path A: C1 excluded from Source B) + `trading/live_paper_runner.py:2013` (`halt_on_critical=True`) | C1 pair-strategy false positives in the intracycle reconciler — already addressed by session 5 Path A. Memo at [`docs/known_issues/2026-05-24_l6_reconciler_posture_during_soak.md`](docs/known_issues/2026-05-24_l6_reconciler_posture_during_soak.md) | `grep -n 'halt_on_critical\|NOT IN' trading/live_paper_runner.py scripts/reconcile_intracycle.py` should show `halt_on_critical=True` + `WHERE strategy NOT IN ('C5b_funding_arb', 'C1_stat_arb')` |
| L7 activity floor monitor | `.github/workflows/activity-floor-monitor.yml` (every 6h on github.com infra) | Crypto book silent for >48h (ML gate stuck / regime detector frozen) — reads `runtime/paper_trades.db` from origin/main | Actions tab → AAATS activity floor monitor; `force_alert=true` via workflow_dispatch for synthetic test; gated by repo variable `LIVENESS_ENABLED=true` |
| L8 drawdown gauges + Grafana alerts | `monitoring/metrics_exporter.py:collect_drawdown` + `deployment/grafana/provisioning/alerting/drawdown_thresholds.yaml` | Per-market drawdown crosses -10% (warn) / -15% (critical) / -20% (page) for >5min sustained. Notifications only — L9 owns the halt. | `curl -s http://aaats-metrics:9091/metrics \| grep aaats_market_dd_pct`. Alert rules visible in Grafana UI under "AAATS / market_drawdown". `aaats-metrics` mounts the named volume `state-crypto-paper:/app/data/state-paper:ro` so it can read `risk_engine_state.paper.json`. |
| L9 persistent auto-halt | `risk/auto_halt.py:check_and_persist_doctrine_halt` (called at top of `run_crypto`, after L5) | Crypto market DD ≤ -20% — sets operator halt (`data/halt_state.json` market=crypto:true) via `foundation/kill_switch.halt`. ONE-WAY trigger: operator must reset manually via `kill.py` on return. Runbook: [`docs/runbooks/operator_return_resume_procedure.md`](docs/runbooks/operator_return_resume_procedure.md) | `cat /home/aaats/aaats/data/halt_state.json` — `crypto: true` set by L9 means operator-return audit is REQUIRED before reset. |
| L10 disk + repo + commit-rate watchdog | `scripts/box/aaats-heartbeat-checker.sh` (the L3 script, extended) | (a) `/home` >85% full, (b) `.git` grew >500MB in 24h, (c) auto-cron commits <80/24h. Each fires via `aaats-cron-alert.sh` with a distinct prefix (`L10/DISK`, `L10/REPO`, `L10/COMMIT_RATE`) and independent per-layer cooldown. | `tail /home/aaats/aaats-heartbeat-checker.log` after a `*/5 * * * *` tick. Synthetic-test recipes in the sprint commit message for `scripts/box/aaats-heartbeat-checker.sh`. |

Operator-return resumption: [`docs/runbooks/operator_return_resume_procedure.md`](docs/runbooks/operator_return_resume_procedure.md). Tailscale-down fallback: [`docs/runbooks/box_unreachable_via_tailscale.md`](docs/runbooks/box_unreachable_via_tailscale.md).

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
