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
# WHAT THIS DOES (two independent jobs)
#   1. TOKEN-HASH WATCH: hash the token in .env. If the hash changed since last
#      tick, the running container is stale -> force-recreate it so it reloads
#      the new token. Rotation now self-applies; no human step.
#   2. LIVENESS WATCH: read the container's Docker health status (set by the L1
#      healthcheck). If it is `unhealthy` / restarting / missing for longer than
#      the grace window, force-recreate once and alert OUT-OF-BAND via
#      aaats-cron-alert.sh (which talks to Telegram directly, bypassing the bot
#      container — so it works even when the bot itself is dead).
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
ALERT_STATE="${ALERT_STATE:-/tmp/aaats-telegram-watchdog-last-alert}"

# Grace window before we treat a non-healthy container as a real fault. The
# healthcheck has start_period=30s + interval=120s; allow a couple of cycles.
UNHEALTHY_GRACE_SEC="${UNHEALTHY_GRACE_SEC:-360}"
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

recreate_bot() {
  local reason="$1"
  log "recreating $SERVICE ($reason)"
  # --no-deps: do not touch sibling containers. --force-recreate: pick up new
  # env even if image/config are unchanged. -p pins the compose project so we
  # don't accidentally act in the aaats-base project.
  if docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" \
        up -d --no-deps --force-recreate "$SERVICE" >/dev/null 2>&1; then
    log "recreate OK"
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
# status is "starting"; a crash-looping container shows "unhealthy" or the
# container is in "restarting"/absent.
HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || echo 'absent')"
STATUS="$(docker inspect --format '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo 'absent')"
log "container status=$STATUS health=$HEALTH"

case "$HEALTH/$STATUS" in
  healthy/running)
    log "bot healthy"
    rm -f "$ALERT_STATE" 2>/dev/null || true   # reset cooldown on recovery
    exit 0
    ;;
  starting/*)
    log "bot still starting — no action"
    exit 0
    ;;
esac

# Anything else (unhealthy, restarting, exited, absent, none/running for too
# long) is a fault. Use a small marker so we only act after the grace window,
# avoiding a fight with a legitimately slow start.
FAULT_MARKER="$STATE_DIR/telegram_unhealthy_since"
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
rm -f "$FAULT_MARKER" 2>/dev/null || true
exit 0
