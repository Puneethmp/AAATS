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

Compose layout: `aaats-paper-crypto` belongs to project `deployment` (config under `/home/aaats/aaats/deployment/`); Grafana/Prometheus belong to project `aaats-base` (config under `/srv/aaats/compose/`). A `compose down` from one path does not touch the other.

## Container has no `sqlite3` CLI

Use `docker exec aaats-paper-crypto python -c "import sqlite3; ..."` for ad-hoc queries.

## Observability — ports & exporters (canonical 2026-05-16)

| Service | Container | Port (host:container) | Notes |
| --- | --- | --- | --- |
| Prometheus exporter | `aaats-metrics` | `9091:9091` | Source: `monitoring/metrics_exporter.py:30`. Image `sha256:79c80b570b95…` (rebuilt 2026-05-16 to bake in `collect_share_equality()`). Scraped by Prometheus per `/srv/aaats/compose/prometheus/prometheus.yml`. Hosts the share-equality counter and all per-strategy gauges. |
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

**Known follow-up**: `aaats-metrics` is attached to the `aaats` network at runtime
via `docker network connect aaats aaats-metrics`. This reverts on container recreate.
Persistent fix requires adding the external `aaats` network to `aaats-metrics`
in `deployment/docker-compose.yml`.
