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
