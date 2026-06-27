# Runbook — Telegram bot self-heal (token rotation + liveness)

**Status:** active · **Owner:** operator · **Added:** 2026-06-25
**Change class:** alert-chain / uptime fix (maintenance-contract exception)

## The problem this solves

The bot reads `ALERTS__TELEGRAM_BOT_TOKEN` from `.env` **once, at process
start**. When the token is rotated, `.env` is updated but the long-lived
container keeps the **old** token in memory and crash-loops on `401
Unauthorized` — while Docker still reports it `Up`. Nothing connected "token
changed" to "recreate the container", so every rotation needed a manual
`docker compose ... up -d --force-recreate aaats-telegram-bot`. In the
2026-05/06 incident the bot ran dead on a revoked token for ~32 days.

Compounding it: the bot **is** the alert channel, so when it dies the thing
meant to warn you is the thing that died.

## The three layers

| Layer | File | Runs where | Catches |
|---|---|---|---|
| **L1** in-container healthcheck | `scripts/telegram_healthcheck.py` + `healthcheck:` block in `deployment/docker-compose.yml` | inside `aaats-telegram-bot` | revoked/invalid token → container goes `unhealthy` instead of fake-`Up` |
| **L3** on-box watchdog | `scripts/box/aaats-telegram-watchdog.sh` → `/home/aaats/bin/`, cron `*/5` | Contabo box | (a) token hash changed → auto-recreate; (b) container unhealthy past grace → auto-recreate + out-of-band alert |
| **L4** off-box liveness | `.github/workflows/telegram-bot-liveness.yml`, cron `*/30` | GitHub infra | token revoked/invalid OR whole box down → alert (independent of the bot) |

L1 makes the failure *visible*. L3 makes it *self-correcting* on the box. L4 is
the independent out-of-band backstop that survives a full-box outage.

## One-time setup

1. **Deploy L1 + L3** from the workstation:
   ```
   python tools/operator/deploy_telegram_selfheal.py --dry-run   # inspect plan
   python tools/operator/deploy_telegram_selfheal.py             # execute
   ```
   The script smoke-verifies the token first, uploads with line-ending
   normalization (`deploy_lib.atomic_upload_normalized`), installs the `*/5`
   cron, recreates only the bot, and seeds the watchdog token-hash baseline.

2. **Enable L4**: the workflow only runs when repo variable
   `LIVENESS_ENABLED=true` (same gate as the existing liveness monitor) and
   needs repo secrets `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`. These already
   exist if `liveness-monitor.yml` is enabled — L4 reuses them. It deploys
   itself on push to `origin/main`.

## After this, rotating the token is a one-liner

Update `.env` on the box and **stop**:
```
ssh aaats@100.95.126.39 \
  "sed -i 's#^ALERTS__TELEGRAM_BOT_TOKEN=.*#ALERTS__TELEGRAM_BOT_TOKEN=<NEW>#' /home/aaats/aaats/.env"
```
Within 5 minutes the L3 watchdog sees the new hash, force-recreates the bot,
and posts a confirmation. **Do not** manually recreate — that's the step we
automated away.

## Verifying it's working

```
# L1 — health status should be `healthy`
ssh aaats@100.95.126.39 "docker inspect --format \
  'status={{.State.Status}} health={{.State.Health.Status}}' aaats-telegram-bot"

# L3 — watchdog log shows ticks; hash baseline exists
ssh aaats@100.95.126.39 "tail /home/aaats/aaats-telegram-watchdog.log; \
  ls -l /srv/aaats/state/telegram_token.hash"

# L4 — Actions tab -> 'AAATS telegram bot liveness'; force a synthetic alert:
#   Run workflow -> force_alert = true
```

## Synthetic failure test (proves the chain)

Point the bot at a deliberately bad token and confirm recovery:
```
ssh aaats@100.95.126.39 '
  cp /home/aaats/aaats/.env /tmp/.env.bak
  sed -i "s#^ALERTS__TELEGRAM_BOT_TOKEN=.*#ALERTS__TELEGRAM_BOT_TOKEN=000:BAD#" /home/aaats/aaats/.env
  docker compose -p deployment -f /home/aaats/aaats/deployment/docker-compose.yml \
    up -d --no-deps --force-recreate aaats-telegram-bot
'
```
A token the server rejects is invalid **at startup**, so the container
crash-loops (see "Failure modes" below) rather than reaching `unhealthy`: Docker
health stays `starting` while `RestartCount` climbs. On the next `*/5` tick the
watchdog detects the climbing `RestartCount` and fires a **crash-loop alert**
(it does *not* recreate — recreate is futile against a bad `.env` token).
Restore the real token (`cp /tmp/.env.bak /home/aaats/aaats/.env`); the **hash
change** then triggers an immediate auto-recreate and a confirmation message.
Clean up `/srv/aaats/state/telegram_unhealthy_since`,
`/srv/aaats/state/telegram_starting_since`, and
`/srv/aaats/state/telegram_last_restartcount` if present.

> **Run drills DETACHED.** Always run break/restore drills under `setsid` with an
> `EXIT` trap that restores the good token, e.g.
> `setsid bash drill.sh >/tmp/drill.log 2>&1 </dev/null &` where `drill.sh` has
> `trap 'cp /tmp/.env.bak "$ENV"; "$WD"' EXIT`. On 2026-06-25 two interactive
> SSH sessions dropped mid-drill — once stranding the bad token in `.env` (alert
> chain down ~10 min), once racing a `pkill` against the recreate and leaving the
> container removed. A detached job with an auto-restore trap survives the drop.

## Two failure shapes (and which layer catches each)

- **Token revoked AFTER the bot is already polling** — the process stays up and
  keeps logging `getUpdates` 401s; the L1 healthcheck (`getMe`) fails, so Docker
  flips the container to `unhealthy` with `RestartCount` **stable**. The
  watchdog's unhealthy-while-running path force-recreates it past the grace
  window (picking up the new `.env` token) and alerts. This is the original
  32-day incident shape.
- **Token invalid AT STARTUP** (server-rejected token in `.env`) — PTB v20 calls
  `getMe` inside `initialize()`, raises `InvalidToken`, the **process exits**,
  and `restart: unless-stopped` restarts it. Each restart resets `start_period`,
  so Docker health is stuck `starting` and **never reaches `unhealthy`**, while
  `RestartCount` climbs. The watchdog's **crash-loop detector** (RestartCount
  increased tick-over-tick AND health != healthy) fires an out-of-band alert and
  **does NOT recreate** — recreate is futile against a bad `.env` token and just
  churns. The fix is a manual `.env` token correction; once `.env` is fixed,
  Job 1's hash-watch auto-recreates onto the good token. (Found 2026-06-25.)

## Failure modes the watchdog still can't self-fix

- **Polling loop hangs but token valid + process up** — `getMe` still returns
  200, so L1 stays green. The watchdog also bounds the `starting` state: a
  container `starting` for `>STARTING_GRACE_SEC` (600s) with stable
  `RestartCount` triggers a one-shot alert. For a hung *polling* loop with a
  valid token, add a bot-side heartbeat file and check its freshness here.
- **Recreate itself fails** (image won't build, disk full) — the watchdog
  alerts out-of-band and stops; this is a genuine incident needing the operator.
- **`.env` has the wrong token** — L3 will faithfully recreate onto a bad
  token; the container then crash-loops, which the crash-loop detector surfaces
  via an alert (and L4 alerts off-box). The fix is still "put the right token in
  `.env`," but now you find out in minutes, not weeks — and the watchdog stops
  churning instead of recreating endlessly.

## Related

- `deploy_lib.verify_telegram_path` / `send_telegram_message` — canonical token
  path is `/home/aaats/aaats/.env` (CLAUDE.md gotcha #11).
- `scripts/box/aaats-cron-alert.sh` — the out-of-band sender L3 uses.
- `docs/decisions/2026-06-25_telegram_selfheal.md` — why, and the contract basis.
