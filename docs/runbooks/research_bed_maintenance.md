# Research-bed maintenance runbook (2026-06-01)

AAATS is in **maintenance / research-bed mode**. The directional-crypto edge program is
terminally closed ([NO-GO verdict](../decisions/2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md));
live-flip is permanently off. The bot runs **paper-only** as an unattended, monitored
research bed; the only live money is the **$25/mo BTC DCA**.

This runbook is the *entire* expected operator interaction. **No code or strategy work is
expected.** The point of "monitored" is that you are pushed when something needs attention
and otherwise do nothing.

## What runs unattended

- **D.5 paper soak** — `aaats-paper-crypto` keeps trading paper on the $110 paper book.
- **Monitoring stack L1–L10** — cron-liveness, ledger-divergence halt, drawdown gauges,
  persistent auto-halt, disk/repo watchdog, plus the Telegram alert chain.

Monitoring verified green on 2026-06-01: L1 (GitHub Actions liveness, `LIVENESS_ENABLED=true`,
recent runs success), L3 (heartbeat watchdog fresh, `*/5` cron active), and the Telegram alert
chain end-to-end (synthetic `getMe`+`sendMessage` both 200 via the canonical `/home/aaats/aaats/.env`
`ALERTS__TELEGRAM_*` path). Re-verify with `python tools/operator/check_engine.py`-style SSH +
`deploy_lib.verify_telegram_path` / `send_telegram_message` if ever in doubt.

## What to glance at, and how often

| Cadence | What | Where |
|---|---|---|
| **Push (no action by default)** | Telegram alerts | Telegram chat `1946109268`. If silent, nothing is wrong — alerts are push-only. |
| **Monthly (optional, ~5 min)** | equity curve / drawdown sanity | Grafana on Tailscale `:3000` (see memory `project_aaats_grafana`). A glance, not a task. |
| **Monthly (operator-only)** | confirm the **$25/mo BTC DCA** recurring buy is still active on the exchange | exchange app — this is the entire live allocation, so it's the one financial thing worth confirming. |

If Telegram has been silent and you want positive confirmation the box is alive:
`cat /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json` (via Tailscale SSH) — `status: ok`
with a recent `last_tick` means cron is pushing.

## If an alert fires

- **L9 persistent auto-halt (crypto market DD ≤ -20%)** — this is a one-way operator-reset trigger.
  Follow [operator_return_resume_procedure.md](operator_return_resume_procedure.md). In research-bed
  mode there is no rush: the book is paper, so the halt protecting nothing live; reset on your own
  schedule after the audit, or leave it halted.
- **Box unreachable via Tailscale** — [box_unreachable_via_tailscale.md](box_unreachable_via_tailscale.md).
- **Auto-cron stopped pushing** — [auto_cron_recovery.md](auto_cron_recovery.md).
- **Anything else** — it can wait. Nothing here risks real money beyond the DCA, which is on the
  exchange, not the bot.

## Grafana shows "No data" on every panel

**This is not a safety-net failure.** Grafana is a *convenience* view; the real monitoring is the
Telegram / L1 (GitHub Actions) / L3 (heartbeat) chain, which is **completely independent of Grafana,
Prometheus, and the exporter**. If Grafana is blank but Telegram is alive and
`auto_cron_heartbeat.json` is fresh, the bed is still monitored — fix Grafana at leisure.

There are exactly two root causes seen for blanket "No data", and both are now guarded at deploy time:

1. **Datasource UID mismatch** (gotcha #10). The provisioned datasource uid is `aaats-prom`, not
   `prometheus`. A dashboard JSON that hard-codes `"uid": "prometheus"` renders "No data" on every
   panel. Check: `grep -o '"uid": "[a-z-]*"' /srv/aaats/compose/grafana/dashboards/*v3*.json | sort | uniq -c`
   — all refs must be `aaats-prom`. Guarded by `deploy_lib.preflight_assert_no_prometheus_uid()`
   (refuses to deploy a stale dashboard) and `grafana_datasource_ref()` (uid right by construction).

2. **Exporter hung** (2026-05-29 incident). `aaats-metrics` served metrics from a single-threaded
   `HTTPServer` with no socket timeout; one blocked client write wedged the only worker thread, so
   Prometheus scrapes timed out (`context deadline exceeded`), `up{job="aaats-metrics"}=0`, every
   `aaats_*` series went stale → dashboard "No data". The dashboard JSON was correct. **Fixed
   permanently**: `metrics_exporter.py` now uses `ThreadingHTTPServer` + a 15s per-request handler
   timeout, so one slow client can no longer wedge the server. Guarded post-deploy by
   `deploy_lib.assert_metrics_flowing()` (asserts `up==1` + a probe metric returns, fails the deploy
   loudly via Telegram otherwise).

   Diagnose fast: `docker ps | grep aaats-metrics` (healthy?), `curl -sS -m8 -w '%{http_code} %{time_total}\n' -o /dev/null localhost:9091/metrics`
   (200 in ~ms = serving; timeout/000 = hung), `docker exec aaats-prometheus wget -qO- --post-data='query=up{job="aaats-metrics"}' http://localhost:9090/api/v1/query`
   (`up=1`?). Recovery: `cd /home/aaats/aaats && docker compose -f deployment/docker-compose.yml up -d --build --no-deps aaats-metrics`
   — or re-run `tools/operator/deploy_exporter_threading_fix_2026_05_29.py` which does the rebuild +
   verification + Telegram alerting in one shot. Prometheus is reachable only inside the
   `aaats-prometheus` container (`:9090` is not host-published) — query it via `docker exec`, not host curl.

## Reactivation

Reactivating the bot for live trading requires a **NEW pre-registered thesis** with its own
committed robustness gate (the discipline that closed the old program: criterion frozen *before*
results, null-controlled, multi-regime out-of-sample). It is **not** a re-run, re-tune, or
re-spec of any closed strategy (C1/C6/C3/C7/TSMOM/ensemble). Absent that, AAATS stays a paper
research bed indefinitely — which is a fine, low-cost steady state (~$6–15/mo opex).

## Explicit won't-do in maintenance mode

Deferred indefinitely unless one of these actually breaks the alert chain: Grafana admin-password
rotation, `deploy_to_contabo.py` retrofit to `deploy_lib`, the stale
`/srv/aaats/secrets/telegram_bot_token` file (the canonical `.env` path is what's used and it works).
