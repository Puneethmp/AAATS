# Runbook — Auto-cron failure recovery

**Audience:** operator or future Claude Code session triaging a Telegram
alert about the auto-cron push stream.
**Author:** 2026-05-24 (Track D reliability sprint).
**Related:** [`2026-05-24_auto_cron_resilience.md`](../decisions/2026-05-24_auto_cron_resilience.md).

## If a Telegram alert just fired, read this first

The alert text tells you which layer fired. Match it:

| Alert text fragment | Source | What it means |
|---|---|---|
| `AAATS LIVENESS ALERT: no auto-cron push for >30min` | **L1** GitHub Actions | Box may be completely down. origin/main hasn't received an auto-cron commit for >30 min. |
| `AAATS CRON: auto-push failed 3x` | **L2** in-cron retry exhaustion | Cron ticked and tried to push; 3 retries with backoff all failed. Likely network or git auth. |
| `AAATS CRON: fetch from origin failed` | **L2** pre-push fetch failure | Cron ticked but couldn't even fetch origin. Network or auth. |
| `AAATS CRON: watchdog: auto-cron heartbeat stale Nmin` | **L3** heartbeat checker | Cron *should* have ticked within the last 20min but the heartbeat file is older. Cron daemon may be dead, or autopush script is hanging silently. |
| `AAATS CRON: watchdog: auto_cron_heartbeat.json missing` | **L3** | Heartbeat file is gone — cron has never run since the file was last cleared, or runtime dir was wiped. |

## 60-second triage

```bash
# From any machine that can SSH:
ssh aaats@100.95.126.39 'bash /home/aaats/bin/aaats-diagnose.sh --quick'
```

That returns heartbeat status, autopush log tail, and cron service state in
<1 second. If that command itself fails, **the box is unreachable** — escalate.

For a full report:

```bash
ssh aaats@100.95.126.39 'bash /home/aaats/bin/aaats-diagnose.sh'
```

## 4-layer architecture

```
+-----------------------------------------------------------------+
| L1 GitHub Actions liveness-monitor (external — outside box)     |
| .github/workflows/liveness-monitor.yml                          |
| Runs every 20 min on github.com infra; alerts if origin/main    |
| has no auto-cron commit in last 30 min. Survives total box      |
| failure. Requires repo secret TELEGRAM_BOT_TOKEN +              |
| TELEGRAM_CHAT_ID + repo variable LIVENESS_ENABLED=true.         |
+-----------------------------------------------------------------+
              |
              |   (independent — alerts even if box is hard-down)
              v
+-----------------------------------------------------------------+
| L2 In-cron robustness (on box)                                  |
| /home/aaats/bin/aaats-autopush.sh (v3 — heartbeat-first)        |
| 1. Write heartbeat status=started PRE-anything                  |
| 2. Fetch + commit + push origin main                            |
| 3. On push failure: retry 3x with 30/60/90s backoff             |
| 4. On final failure: fire Telegram via cron_alert.sh +          |
|    write heartbeat status=push_failed                           |
+-----------------------------------------------------------------+
              |
              |   (cron_alert.sh hits api.telegram.org directly,
              |    bypassing aaats-telegram-bot container)
              v
+-----------------------------------------------------------------+
| L3 Heartbeat freshness checker (on box, independent cron job)   |
| /home/aaats/bin/aaats-heartbeat-checker.sh                      |
| Crontab: */5 * * * * — runs every 5 min                         |
| Reads /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json  |
| Alerts if last_tick > 20 min old (cron daemon may be dead, or   |
| autopush is hanging mid-script).                                |
| 1-hour cooldown between repeat alerts to prevent spam.          |
+-----------------------------------------------------------------+
              |
              |   (when triaging, run this for full state:)
              v
+-----------------------------------------------------------------+
| L4 Self-diagnosis (on box, on-demand)                           |
| /home/aaats/bin/aaats-diagnose.sh [--quick]                     |
| Prints markdown report: heartbeat, autopush log, cron status,   |
| crontab, containers, runtime_repo git state, network, disk/mem. |
+-----------------------------------------------------------------+
```

## Symptom → diagnostic → fix

### Symptom: L1 fired (no commits in 30min) but box is reachable via SSH

```bash
ssh aaats@100.95.126.39 'bash /home/aaats/bin/aaats-diagnose.sh'
```

Look at the heartbeat section. Three cases:

- **Heartbeat fresh, status=ok, last_push fresh** — race condition: cron
  pushed just after L1's window. Check next L1 run; if still firing,
  inspect github.com side (rate limit? deploy key revoked?).
- **Heartbeat fresh, status=push_failed** — L2 retries exhausted. Check
  autopush log for git error. Likely network or auth.
  ```bash
  ssh aaats@100.95.126.39 'tail -50 /home/aaats/aaats-autopush.log'
  ```
- **Heartbeat stale (>20min)** — autopush hung or cron daemon stopped.
  ```bash
  ssh aaats@100.95.126.39 'systemctl status cron; ps -ef | grep autopush'
  ```
  Restart cron if needed: `sudo systemctl restart cron`. If autopush
  process is hung, kill it: `pkill -f aaats-autopush`. Lock will auto-clear.

### Symptom: L2 fired (push failed 3x)

```bash
ssh aaats@100.95.126.39 'tail -80 /home/aaats/aaats-autopush.log | grep -E "(===|push|fetch|alert|FAILED)"'
```

Common causes:
- **Deploy key revoked** — `git push --dry-run` on box says "Permission denied".
  Operator action: re-issue deploy key in GitHub repo settings.
- **Network egress blocked** — `curl github.com` times out. Check Tailscale,
  check Contabo network status, check `iptables -L OUTPUT`.
- **Non-fast-forward push** — workstation pushed something the box can't
  rebase onto. Inspect: `cd /srv/aaats/runtime_repo && git status`.
  Usually heals on next tick because v3 does `git pull --rebase` between retries.

### Symptom: L3 fired (heartbeat stale)

```bash
ssh aaats@100.95.126.39 'systemctl is-active cron; cat /srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json; tail -5 /home/aaats/aaats-heartbeat-checker.log'
```

- **cron service inactive** — `sudo systemctl start cron && sudo systemctl enable cron`.
- **heartbeat shows status=started but old last_tick** — autopush hung
  mid-tick (likely during docker cp of a large file or a python jq call).
  Kill the autopush process; next tick should recover.
- **heartbeat file missing** — runtime dir was wiped, or first cron tick
  never ran after a fresh deploy. Force a tick:
  `ssh aaats@100.95.126.39 '/home/aaats/bin/aaats-autopush.sh'`.

## One-shot rollback (return to v2 if v3 misbehaves)

```bash
ssh aaats@100.95.126.39 'cp /home/aaats/bin/aaats-autopush.sh.v2.bak.20260524T095413Z /home/aaats/bin/aaats-autopush.sh && chmod +x /home/aaats/bin/aaats-autopush.sh && crontab -l | grep -v aaats-heartbeat-checker | crontab -'
```

L1 (GitHub Actions) can be disabled by setting repo variable
`LIVENESS_ENABLED=false` (or deleting it). The workflow file itself
stays in the repo.

## Enabling L1 (one-time operator action)

L1 ships with `if: vars.LIVENESS_ENABLED == 'true'` — the job is skipped
until the operator confirms the secrets are set.

1. In GitHub repo Settings → Secrets and variables → Actions → Secrets:
   - Add `TELEGRAM_BOT_TOKEN` (value: same as `ALERTS__TELEGRAM_BOT_TOKEN` in box `.env`).
   - Add `TELEGRAM_CHAT_ID` (value: `1946109268`).
2. In Settings → Secrets and variables → Actions → Variables:
   - Add `LIVENESS_ENABLED` with value `true`.
3. Trigger a dry run from the Actions tab → AAATS liveness monitor →
   Run workflow → set "force_alert" to `true` → Run. Confirm Telegram fires.
4. Set `force_alert` back to `false` for normal runs.

If you skip step 3, the workflow will start firing real alerts on the
next stale window.

## Known limits

This 4-layer system does NOT catch:

- **Simultaneous failure of github.com AND Telegram** — L1 needs both. If
  both go down at the same time, alert chain breaks.
- **Silent data corruption that still pushes** — if the autopush script
  pushes corrupt or stale-content commits successfully, L1 sees a "push" and
  stays green. Defended elsewhere by share-equality alert + reconciler.
- **Tailscale outage** — operator's SSH access is gated by Tailscale; the
  alerts still fire (Telegram is over public internet), but operator can't
  SSH in to fix. Workaround: Contabo VNC console.
- **GitHub Actions runner quota exhausted** — free tier resets monthly;
  if budget runs out, L1 stops running silently. Check the Actions tab
  weekly during long soaks.
