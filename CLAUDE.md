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

## Observability — ports & exporters (canonical 2026-05-15)

| Service | Container | Port (host:container) | Notes |
| --- | --- | --- | --- |
| Prometheus exporter | `aaats-metrics` | `9091:9091` | Source: `monitoring/metrics_exporter.py:30`. Scraped by Prometheus per `deployment/prometheus/prometheus.yml`. Hosts the share-equality counter and all per-strategy gauges. |
| Trading container | `aaats-paper-crypto` | (none) | Exposes no ports; metrics are surfaced by `aaats-metrics` reading shared `data/` bind mounts. |
| Grafana | `aaats-grafana` | Tailscale-only on `:3000` | See memory `project_aaats_grafana.md`. |

If a script or doc references `aaats-paper-crypto:8001`, it is stale — that
endpoint was retired when the exporter was split into the standalone
`aaats-metrics` container. Don't resurrect it without compose changes.
