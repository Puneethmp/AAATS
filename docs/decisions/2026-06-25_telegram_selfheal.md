# Decision — automate Telegram bot token reload + liveness (self-heal)

**Date:** 2026-06-25
**Status:** proposed (change set staged, awaiting operator sign-off to deploy)
**Change class:** alert-chain / uptime fix
**Contract basis:** CLAUDE.md "MAINTENANCE CONTRACT" permits exactly two change
classes — (1) security patches and (2) T3-collector-uptime fixes — plus
restoring the monitoring stack to green. This change is an alert-chain
restoration: it hardens the channel that carries the three permitted alerts
(entry tripwire / OI gap / health red). It touches `monitoring/` only by adding
a healthcheck **around** the bot, not by changing trading/risk/execution logic.

## Context

The Telegram bot has been manually fixed at least twice for the same root
cause. Most recent: the container crash-looped on a **revoked token for ~32
days** (rotated ~2026-05-24; `.env` updated, container never recreated) until a
human noticed. This is the alert channel for the entire maintenance posture —
when it is silently dead, the system's "stay healthy, keep collecting" contract
has no working tripwire.

## Root cause

"Config rotated but process not reloaded." The bot reads
`ALERTS__TELEGRAM_BOT_TOKEN` once at start (`monitoring/telegram_bot.py:46`).
Three things must happen on rotation; only one did:

1. ✅ `.env` updated with new token
2. ❌ container recreated to reload env
3. ❌ validation that the live process has a *working* token

`restart: unless-stopped` faithfully restarted the container back onto the same
dead token. And because the bot is itself the alert channel, its death was
invisible — a self-referential monitoring hole.

## Decision

Add three independent layers, mirroring the existing L1–L10 monitoring design
rather than inventing a new pattern:

- **L1 — in-container token-valid healthcheck** (`scripts/telegram_healthcheck.py`,
  wired in `deployment/docker-compose.yml`). Calls `getMe` with the bot's own
  token. Revoked token → `unhealthy`, not fake-`Up`.
- **L3 — on-box watchdog** (`scripts/box/aaats-telegram-watchdog.sh`, cron `*/5`).
  Hashes the `.env` token; on change, force-recreates the bot so rotation
  self-applies. Also recovers an `unhealthy`/restarting container and alerts
  out-of-band via `aaats-cron-alert.sh`.
- **L4 — off-box GitHub Actions check** (`.github/workflows/telegram-bot-liveness.yml`,
  cron `*/30`, gated on `LIVENESS_ENABLED`). Independent `getMe` probe that
  also fires if the whole box is down. Breaks the circular dependency.

Deploy via `tools/operator/deploy_telegram_selfheal.py` (uses `deploy_lib`:
UTF-8 console, atomic normalized upload, telegram smoke-verify before any
destructive step, recreate `--no-deps` so siblings are untouched).

## Options considered

1. **Keep fixing manually** — rejected. Mean-time-to-detect was ~weeks; the
   failure recurs on every rotation.
2. **`autoheal` sidecar only (L1+L2)** — would recreate an unhealthy container
   but, without the token-hash watch, recreates onto the *same* stale token
   when the problem is a rotation. Doesn't fix the root cause; skipped in favor
   of L3. Can be added later for hands-off recovery if desired.
3. **Bot-side hot token reload** (re-read `.env` on a timer / SIGHUP) — more
   bot code in maintenance mode, and still wouldn't catch a hung process.
   Rejected as larger surface for smaller coverage.
4. **L1 + L3 + L4 (chosen)** — smallest change that makes rotation self-apply
   (L3), makes failure visible (L1), and keeps an independent out-of-band
   backstop (L4). Reuses existing alert plumbing and secrets.

## Scope / non-goals

- No change to `trading/`, `risk/`, `execution/`, or the entry-disabled posture.
- The bot stays flat-book read-only; `/killall` etc. unchanged.
- Does **not** rotate the stale `/srv/aaats/secrets/telegram_bot_token`
  (CLAUDE.md known footgun) — but L3/L4 read only the canonical `.env`, so the
  stale file is now inert. Recommend deleting it in a later cleanup.

## Residual risk

- Polling-hang with a valid token stays green to L1 (documented in the runbook;
  rare for python-telegram-bot v20).
- A failed recreate (disk full / build break) is escalated out-of-band as a
  real incident, not auto-fixed.

## Verification

Synthetic bad-token test in `docs/runbooks/telegram_bot_selfheal.md` proves the
full chain (unhealthy → watchdog detect → restore → hash-change auto-recreate →
confirmation). L4 has a `force_alert=true` dispatch for an out-of-band synthetic.
