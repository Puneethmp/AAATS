#!/usr/bin/env bash
# AAATS Telegram bot watchdog (L3) — makes token rotation self-applying and
# auto-recovers a dead/unhealthy bot container.
#
# THE BUG THIS KILLS
# ------------------
# The bot reads ALERTS__TELEGRAM_BOT_TOKEN from .env exactly once, at process
# start. When the token is rotated, .env is updated but the long-lived
# container keeps the OLD token in memory and crash-loops on 401 — for 32 days
# in the 2026-05/06 incident — while Docker still shows it "Up". Nothing
# connected "token changed" to "recreate the container", so it was a manual fix
# every single time.
#
# WHAT THIS DOES (independent jobs)
#   1. TOKEN-HASH WATCH: hash the token in .env. If the hash changed since last
#      tick, the running container is stale -> force-recreate it so it reloads
#      the new token. Rotation now self-applies; no human step.
#   2. LIVENESS WATCH: read the container's Docker health status (set by the L1
#      healthcheck).
#        a. UNHEALTHY-WHILE-RUNNING (process up, RestartCount stable, health
#           unhealthy — e.g. token revoked AFTER the bot was already polling):
#           force-recreate once past a grace window and alert OUT-OF-BAND.
#        b. CRASH-LOOP (RestartCount climbing tick-over-tick, health != healthy —
#           e.g. token rejected by the server AT STARTUP, so PTB raises
#           InvalidToken inside initialize(), the process exits, and
#           `restart: unless-stopped` restarts it; each restart resets
#           start_period so Docker health is stuck `starting` and NEVER reaches
#           `unhealthy`): ALERT OUT-OF-BAND and DO NOT recreate — recreate is
#           futile against a bad .env token and just churns. The fix is a manual
#           .env token correction. (Found in the 2026-06-25 synthetic drill.)
#        c. STUCK-STARTING (health `starting` beyond a bounded window with
#           RestartCount stable — genuinely slow start or a hung healthcheck,
#           not a loop): alert once.
#      Out-of-band alerts go via aaats-cron-alert.sh, which talks to Telegram
#      directly, bypassing the bot container — so it works even when the bot
#      itself is dead.
#
# This is the on-box half. The GitHub Actions check (L4,
# .github/workflows/telegram-bot-liveness.yml) is the off-box half that still
# fires if the entire box is down.
#
# SCHEDULING: run every 5 min, same cadence as aaats-heartbeat-checker.sh.
#   crontab:  */5 * * * * /home/aaats/bin/aaats-telegram-watchdog.sh >> /home/aaats/aaats-telegram-watchdog.log 2>&1
#   (or a systemd timer mirroring aaats-heartbeat-checker.timer)
#
# Source-of-truth: scripts/box/aaats-telegram-watchdog.sh in the AAATS repo.
# Deployed location on box: /home/aaats/bin/aaats-telegram-watchdog.sh
set -uo pipefail

ENV_FILE="${ENV_FILE:-/home/aaats/aaats/.env}"
COMPOSE_FILE="${COMPOSE_FILE:-/home/aaats/aaats/deployment/docker-compose.yml}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-deployment}"
SERVICE="${SERVICE:-aaats-telegram-bot}"
CONTAINER="${CONTAINER:-aaats-telegram-bot}"
ALERT="${ALERT:-/home/aaats/bin/aaats-cron-alert.sh}"

# State files (survive reboots; /srv is the durable runtime area on the box).
STATE_DIR="${STATE_DIR:-/srv/aaats/state}"
HASH_FILE="${HASH_FILE:-$STATE_DIR/telegram_token.hash}"
RC_FILE="${RC_FILE:-$STATE_DIR/telegram_last_restartcount}"
FAULT_MARKER="${FAULT_MARKER:-$STATE_DIR/telegram_unhealthy_since}"
STARTING_MARKER="${STARTING_MARKER:-$STATE_DIR/telegram_starting_since}"
ALERT_STATE="${ALERT_STATE:-/tmp/aaats-telegram-watchdog-last-alert}"

# Grace window before we treat a non-healthy (but not crash-looping) container as
# a real fault. The healthcheck has start_period=30s + interval=120s; allow a
# couple of cycles.
UNHEALTHY_GRACE_SEC="${UNHEALTHY_GRACE_SEC:-360}"
# How long a container may sit in `starting` (with stable RestartCount) before we
# treat it as stuck and alert.
STARTING_GRACE_SEC="${STARTING_GRACE_SEC:-600}"
COOLDOWN_SEC="${COOLDOWN_SEC:-3600}"   # one alert per hour max

NOW=$(date -u +%s)
WHEN=$(date -u +%FT%TZ)
mkdir -p "$STATE_DIR" 2>/dev/null || true

log() { echo "[$WHEN] $*"; }

fire_alert_once() {
  local msg="$1"
  local last=0
  [ -f "$ALERT_STATE" ] && last=$(cat "$ALERT_STATE" 2>/dev/null || echo 0)
  if [ $((NOW - last)) -lt "$COOLDOWN_SEC" ]; then
    log "alert suppressed (cooldown): $msg"
    return 0
  fi
  if [ -x "$ALERT" ]; then
    "$ALERT" "telegram-watchdog: $msg" || log "ALERT helper failed"
  else
    log "ALERT helper missing at $ALERT — cannot send: $msg"
  fi
  echo "$NOW" > "$ALERT_STATE"
}

# Drop the per-container state markers so the next tick re-baselines cleanly
# against the freshly-created container (which starts at RestartCount=0). Called
# after any legit recreate so a healthy new container never false-positives the
# crash-loop check.
reset_container_state() {
  rm -f "$RC_FILE" "$FAULT_MARKER" "$STARTING_MARKER" 2>/dev/null || true
}

recreate_bot() {
  local reason="$1"
  log "recreating $SERVICE ($reason)"
  # --no-deps: do not touch sibling containers. --force-recreate: pick up new
  # env even if image/config are unchanged. -p pins the compose project so we
  # don't accidentally act in the aaats-base project.
  if docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" \
        up -d --no-deps --force-recreate "$SERVICE" >/dev/null 2>&1; then
    log "recreate OK"
    reset_container_state
    return 0
  fi
  log "recreate FAILED"
  return 1
}

# ── Preconditions ────────────────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  fire_alert_once "ENV_FILE missing ($ENV_FILE) — cannot manage bot token"
  exit 1
fi

TOKEN="$(grep -E '^ALERTS__TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 \
          | cut -d= -f2- | tr -d '"' | tr -d "'" | tr -d '[:space:]')"
if [ -z "$TOKEN" ]; then
  fire_alert_once "ALERTS__TELEGRAM_BOT_TOKEN empty in .env"
  exit 2
fi

# ── Job 1: token-hash watch ──────────────────────────────────────────────────
# We store only the SHA-256 of the token, never the token itself.
CUR_HASH="$(printf '%s' "$TOKEN" | sha256sum | cut -d' ' -f1)"
PREV_HASH=""
[ -f "$HASH_FILE" ] && PREV_HASH="$(cat "$HASH_FILE" 2>/dev/null || echo '')"

if [ -z "$PREV_HASH" ]; then
  # First run: record baseline, don't recreate.
  echo "$CUR_HASH" > "$HASH_FILE"
  log "token hash baseline recorded"
elif [ "$CUR_HASH" != "$PREV_HASH" ]; then
  log "token hash CHANGED — rotation detected"
  if recreate_bot "token rotated"; then
    echo "$CUR_HASH" > "$HASH_FILE"
    fire_alert_once "token rotation detected; bot recreated to reload new token"
  else
    fire_alert_once "token rotated but bot recreate FAILED — manual action needed"
  fi
  # Recreate just happened; let the next tick assess health.
  exit 0
fi

# ── Job 2: liveness / health watch ───────────────────────────────────────────
# State of the container per Docker. If no healthcheck has reported yet the
# status is "starting"; a container whose process stays up but fails the
# healthcheck shows "unhealthy"; a crash-looping container keeps resetting to
# "starting" while its RestartCount climbs.
HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || echo 'absent')"
STATUS="$(docker inspect --format '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo 'absent')"
CUR_RC="$(docker inspect --format '{{.RestartCount}}' "$CONTAINER" 2>/dev/null || echo '-1')"

# Load the previous RestartCount, then persist the current one for the next tick.
# Only persist a real (>=0) count so an absent container never poisons the
# baseline with -1 (which would look like an increase when it returns at 0).
PREV_RC=""
[ -f "$RC_FILE" ] && PREV_RC="$(cat "$RC_FILE" 2>/dev/null || echo '')"
if [ "$CUR_RC" -ge 0 ] 2>/dev/null; then
  echo "$CUR_RC" > "$RC_FILE"
fi

log "container status=$STATUS health=$HEALTH restarts=$CUR_RC (prev=${PREV_RC:-none})"

# Did RestartCount increase since the last tick? (Both sides must be real counts;
# a recreate resets RC to 0, yielding a non-positive delta -> never a false loop.)
RC_INCREASED=0
if [ -n "$PREV_RC" ] && [ "$CUR_RC" -ge 0 ] 2>/dev/null \
   && [ "$PREV_RC" -ge 0 ] 2>/dev/null && [ "$CUR_RC" -gt "$PREV_RC" ]; then
  RC_INCREASED=1
fi

# ── Job 2b: crash-loop detection (alert only; recreate is futile) ────────────
if [ "$RC_INCREASED" -eq 1 ] && [ "$HEALTH" != "healthy" ]; then
  log "CRASH-LOOP: RestartCount ${PREV_RC}->${CUR_RC}, health=$HEALTH — alert, NO recreate"
  fire_alert_once "bot CRASH-LOOPING (RestartCount ${PREV_RC}->${CUR_RC}, health=$HEALTH). The token in .env is almost certainly INVALID AT STARTUP — PTB calls getMe in initialize(), the process exits, and Docker health stays 'starting' forever. Recreate won't help: fix ALERTS__TELEGRAM_BOT_TOKEN in $ENV_FILE (then L3 hash-watch auto-recreates)."
  exit 0
fi

case "$HEALTH/$STATUS" in
  healthy/running)
    log "bot healthy"
    # Recovered: reset cooldown + clear any lingering grace markers.
    rm -f "$ALERT_STATE" "$FAULT_MARKER" "$STARTING_MARKER" 2>/dev/null || true
    exit 0
    ;;
  starting/*)
    # Not a crash-loop (RestartCount stable, else we'd have alerted above).
    # Bound the starting state so a genuinely-stuck container is surfaced.
    if [ ! -f "$STARTING_MARKER" ]; then
      echo "$NOW" > "$STARTING_MARKER"
      log "bot starting — begin start-grace timer"
      exit 0
    fi
    S_SINCE=$(cat "$STARTING_MARKER" 2>/dev/null || echo "$NOW")
    S_AGE=$((NOW - S_SINCE))
    if [ "$S_AGE" -ge "$STARTING_GRACE_SEC" ]; then
      log "stuck in 'starting' for ${S_AGE}s (RestartCount stable) — alerting"
      fire_alert_once "bot stuck in 'starting' for ${S_AGE}s with stable RestartCount — the healthcheck never went green though the process isn't crash-looping. Investigate (token network reach? healthcheck hang?)."
    else
      log "bot starting for ${S_AGE}s (< ${STARTING_GRACE_SEC}s) — waiting"
    fi
    exit 0
    ;;
esac

# Anything else (unhealthy / restarting / exited / absent) with a STABLE
# RestartCount is the recreate-worthy fault: the process is up (or gone) but the
# healthcheck fails — e.g. the original incident shape (token revoked after the
# bot was already polling). Use a marker so we only act after the grace window,
# avoiding a fight with a legitimately slow start.
rm -f "$STARTING_MARKER" 2>/dev/null || true   # no longer "starting"
if [ ! -f "$FAULT_MARKER" ]; then
  echo "$NOW" > "$FAULT_MARKER"
  log "first unhealthy observation — starting grace timer"
  exit 0
fi
SINCE=$(cat "$FAULT_MARKER" 2>/dev/null || echo "$NOW")
FAULT_AGE=$((NOW - SINCE))

if [ "$FAULT_AGE" -lt "$UNHEALTHY_GRACE_SEC" ]; then
  log "unhealthy for ${FAULT_AGE}s (< ${UNHEALTHY_GRACE_SEC}s grace) — waiting"
  exit 0
fi

log "unhealthy for ${FAULT_AGE}s (>= grace) — recovering"
if recreate_bot "unhealthy=$HEALTH status=$STATUS for ${FAULT_AGE}s"; then
  fire_alert_once "bot was $HEALTH/$STATUS for ${FAULT_AGE}s; auto-recreated. Verify /status responds."
else
  fire_alert_once "bot $HEALTH/$STATUS for ${FAULT_AGE}s and recreate FAILED — manual action needed"
fi
# recreate_bot already cleared the markers on success; clear here too in case it
# failed, so a persistent fault re-arms the grace timer rather than instantly
# re-recreating every tick.
rm -f "$FAULT_MARKER" 2>/dev/null || true
exit 0
