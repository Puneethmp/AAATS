# Auto-cron resilience — 4-layer defense in depth

**Date:** 2026-05-24
**Status:** SHIPPED. All 4 layers deployed; L1 gated on operator action (secrets).
**Trigger:** Investigation of a suspected 15h auto-cron blackout that turned
out to be a stale-fetch illusion on the workstation. The investigation
exposed real resilience gaps unrelated to the false positive.

## Decision

The auto-cron push stream from the Contabo box to origin/main is the
operator's primary signal of bot liveness during the 30-day D.5 soak.
Before operator-away departure (2026-05-25), build four independent
layers so that any single failure is caught by at least one other layer
*and* surfaced externally via Telegram.

Architecture (full diagram in [`docs/runbooks/auto_cron_recovery.md`](../runbooks/auto_cron_recovery.md)):

1. **L1** — GitHub Actions liveness-monitor: external to the box, alerts
   if origin/main has no auto-cron commit in the last 30 min.
2. **L2** — `aaats-autopush v3` on box: writes heartbeat pre-push (so we
   distinguish "cron ran" from "push succeeded"), retries 3x on push
   failure, fires Telegram via standalone `cron_alert.sh` (bypasses the
   bot container, which itself could be down).
3. **L3** — `aaats-heartbeat-checker.sh` cron job: every 5 min, reads
   the heartbeat file and alerts via Telegram if `last_tick` > 20 min old.
   Has 1-hour alert cooldown to prevent spam.
4. **L4** — `aaats-diagnose.sh`: one-shot operator/Claude diagnostic
   tool. `--quick` returns under 100ms for cheap polling; full mode
   covers heartbeat, autopush log, cron, crontab, containers,
   runtime_repo git state, network, disk/mem.

## Why 4 layers, not 1

Each layer covers a different failure class:

| Failure class | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| Box hard-down (cron + everything) | ✅ | ❌ | ❌ | ❌ |
| Cron daemon dead, box otherwise up | ✅ | ❌ | ✅ (via missed heartbeat) | ❌ |
| Cron runs, git push fails (auth/network) | ✅ (after 30min) | ✅ (immediately) | ❌ | ❌ |
| Cron runs, autopush hangs mid-script | ✅ (after 30min) | ❌ | ✅ (stale heartbeat) | ❌ |
| Operator wants to triage on-demand | — | — | — | ✅ |

Three of the four failure classes are covered by ≥2 layers — that's the
defense-in-depth budget paying for itself. The one single-coverage class
(box hard-down) is the most catastrophic and *must* be covered externally;
L1 is the only layer that can survive total box failure.

## Why GitHub Actions for the external monitor

Alternatives rejected:

- **Uptime Kuma** — requires a separate VPS or the operator's home
  machine being on; introduces a second box that itself can go down.
- **Healthchecks.io** — third-party dependency; the free tier is enough
  but adds an external service whose availability we don't control.
- **Systemd-only on box** — still inside the failed system; can't catch
  the "box hard-down" case at all.
- **Heroku / Railway scheduler** — paid; not justified for one cron job.

GitHub Actions is free (within standard repo limits), runs on infra
completely independent of our box, has built-in secret storage for the
Telegram token, and the workflow file lives in the same repo so version
control is automatic.

## Why heartbeat pre-push (status=started before any work)

If the heartbeat were written *after* push success, "heartbeat fresh"
would conflate two things: "cron ran" AND "push succeeded". The
investigation that prompted this work demonstrated exactly that
ambiguity — `git log origin/main` was the only signal, and a stale
local cache made it look like no commits had landed for 15h.

By writing a heartbeat the moment cron enters the script (status="started"),
and re-writing with status="ok" / "push_failed" / "fetch_failed" at the
end, the system distinguishes:

- heartbeat fresh + status=ok → fully healthy
- heartbeat fresh + status=push_failed → cron ran but couldn't ship → L2 alert
- heartbeat fresh + status=fetch_failed → cron ran but origin unreachable → L2 alert
- heartbeat stale + status=started → autopush hung mid-script → L3 alert
- heartbeat missing → cron never ran since runtime dir was last cleared → L3 alert

This is what makes L3 useful at all. Without a pre-push heartbeat, L3 could
only check "did origin/main get a commit recently" — which is what L1
already does, externally and more reliably.

## Trade-off: L3 via cron vs systemd timer

The original sketch put L3 on a systemd timer for stronger independence
from the cron daemon. Installing a systemd unit requires root and the
deploy account doesn't have passwordless sudo. Cron is the pragmatic
choice for now — same failure mode as the cron daemon means *both* L2
and L3 die together if cron dies, but L1 (external) catches that exact
case.

The systemd unit files are checked into `scripts/box/aaats-heartbeat-checker.{service,timer}`
as the operator-led upgrade path. Switch by:

```bash
sudo cp scripts/box/aaats-heartbeat-checker.service /etc/systemd/system/
sudo cp scripts/box/aaats-heartbeat-checker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aaats-heartbeat-checker.timer
crontab -l | grep -v aaats-heartbeat-checker | crontab -  # remove cron entry
```

## Why cron_alert.sh bypasses the aaats-telegram-bot container

If the box is in a state where cron is failing, the telegram-bot
container may also be in a degraded state (shared host, shared docker
daemon, shared network). Sending Telegram via `curl` directly to
`api.telegram.org` removes the bot container from the alert path.
The bot's API token is just an HTTPS bearer; no helper code needed.

## What this is NOT

- Not a fix to any specific bug — the alleged 15h blackout never happened
  (see [`docs/known_issues/2026-05-24_cron_blackout_false_positive.md`](../known_issues/2026-05-24_cron_blackout_false_positive.md)).
- Not a replacement for `share_equality_mismatch`, `kill_trigger_paths`, or
  any of the other content-correctness signals. L1-L4 only cover
  liveness (did the cron tick, did the push land). A push of corrupted
  content still shows as green here.
- Not a license to skip the operator-return Telegram check; pager queue
  is the higher-resolution signal during soak.
