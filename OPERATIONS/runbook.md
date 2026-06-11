# AAATS Maintenance Runbook (zero-touch contract, 2026-06-11)

> The system's job until the 2027 review: **stay flat, stay healthy, keep
> collecting.** This document is everything the operator needs; nothing here
> requires Claude or a dev environment.

## What is running, where

| Thing | Where | Why it still runs |
|---|---|---|
| `aaats-paper-crypto` container | Contabo box `aaats@100.95.126.39` (Tailscale), `/home/aaats/aaats`, compose project `deployment/` | exit-only research bed; entries disabled (`ENTRIES_DISABLED`, 2026-06-10). Book is FLAT since 2026-06-11T08:58Z and must stay flat |
| T3 OI collector | host cron hourly (`aaats-t3-oi-collector.py`) → `/home/aaats/t3/t3_positioning.db` | **the only live research thread** — 9 months of hourly OI needed; earliest valid test ≈ 2027-03-06. DO NOT DELETE; not in git, backed up daily by `aaats-t3-backup.sh` |
| Auto-cron push | host cron `*/15` (`aaats-autopush.sh` → v3) | publishes `runtime/` snapshots to origin/main; feeds L1 liveness + weekly report distribution |
| Grafana/Prometheus/metrics/watchdog/telegram-bot | compose project `aaats-base` (`/srv/aaats/compose/`) + `deployment/` | monitoring stack |
| BTC DCA $25/mo | exchange-side recurring buy | the only live money; not touched by any of this |

## Start / stop the box services

```bash
# status
ssh aaats@100.95.126.39 'docker ps --format "{{.Names}}: {{.Status}}"'
# stop / start the trading loop only (siblings untouched)
ssh aaats@100.95.126.39 'cd /home/aaats/aaats && docker compose -f deployment/docker-compose.yml stop aaats-paper-crypto'
ssh aaats@100.95.126.39 'cd /home/aaats/aaats && docker compose -f deployment/docker-compose.yml up -d aaats-paper-crypto'
# whole-box reboot: everything is restart: unless-stopped + cron; it self-heals.
```

## Where logs live

- Container: `docker logs aaats-paper-crypto` (NOT pushed to GitHub — security fix 2026-06-10)
- Runner file log: `/home/aaats/aaats/logs/` (bind mount)
- Cron watchdogs: `/home/aaats/aaats-heartbeat-checker.log`, `/home/aaats/t3/{collector,watchdog,backup}.log`
- Heartbeat (canonical "is cron alive"): `/srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json`

## The weekly report — your only required contact surface

Generated **Mondays 06:10 UTC** by box cron (`aaats-weekly-report.sh`) and
published to **origin/main → `runtime/REPORTS/week_NN.md`** (readable on
GitHub, no SSH). It contains: net-of-cost ledger vs the $0 no-trade baseline
(should be trivially $0 vs $0 now the book is flat), open-book status
(should be EMPTY), OI collector health (row counts, last-7d coverage, disk),
and health anomalies. **If the weekly report looks boring, the system is
working.**

## Alerts — exactly three conditions (Telegram chat 1946109268)

| # | Condition | Fired by | Action on receipt |
|---|---|---|---|
| (a) | **Any entry event** (impossible by design) | `aaats-entry-tripwire.sh`, cron `*/30` | Treat as incident. `docker logs aaats-paper-crypto \| grep -iE 'entry\|buy'`; check `ENTRIES_DISABLED` flags; roll back via the manifest if a bad deploy caused it |
| (b) | **OI collector gap** (>2 h stale; unrecoverable at >30 d) | `aaats-t3-watchdog.sh`, cron `*/30` | `tail /home/aaats/t3/collector.log`; re-run collector once by hand; check disk; a gap >30 d kills the T3 thesis — act within days, not weeks |
| (c) | **Health red** (heartbeat stale >20 min / cron dead >30 min / disk >85%) | L3 `aaats-heartbeat-checker.sh` + L1 GitHub liveness + L10 | runbooks: `docs/runbooks/auto_cron_recovery.md`, `docs/runbooks/box_unreachable_via_tailscale.md` |

Everything else is silenced: daily digest schedule OFF, L7 activity-floor
schedule OFF (a quiet book is the goal now). Grafana L8 drawdown rules remain
installed but cannot fire on a flat book.

## Rollback procedure (research-bed deploy)

Manifest: `.rollback/2026-06-10_research_bed_posture/MANIFEST.txt` — box
backups are `<path>.bak-20260610T170412Z`, removed modules are
`<path>.removed-20260610T170412Z`; restore + `docker compose -f
deployment/docker-compose.yml up -d --build --no-deps aaats-paper-crypto`,
then `git revert 1c39dde3` on the workstation to keep repo/box in sync.

## Security / rotation

Rotation table + incident record: `AUDIT/security_closeout.md`. Open operator
items as of 2026-06-11: **make the repo private**, re-key the Angel One TOTP
seed, rotate the Cloudflare tunnel token and Grafana admin password. Every
push (including box auto-pushes) is now gitleaks-scanned in CI
(`.github/workflows/gitleaks.yml`).

## Reopen criteria (the only path back to trading)

Per the standing program closure (CLAUDE.md) and the pre-registration
framework, **nothing reopens before the T3 data gate**:

- **When:** earliest valid run ≈ **2027-03-06** (≥9 months of continuous
  hourly OI from 2026-06-06; no gap >30 days).
- **What evidence would justify reopening:** the T3 OI-crowding thesis —
  positioning information NOT present in price — passing the frozen 15-fold
  null-controlled walk-forward gate in
  `docs/decisions/2026-06-06_reactivation_thesis_portfolio_preregistration.md`
  §3, executed per `docs/closeout/T3_REOPEN_CHECKLIST.md` with the existing
  harness (`tools/nautilus/basket_ledger.py`, `xsect_walkforward.py`,
  `null_engines.py`) **unmodified**.
- **What does NOT justify reopening:** any re-tune of a falsified mechanism
  (`research/falsified.md` is terminal), any "the market changed" intuition,
  any backtest on price-derived signals. Every price/funding/basis family is
  already falsified.
