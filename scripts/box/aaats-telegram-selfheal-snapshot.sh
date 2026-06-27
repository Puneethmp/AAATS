#!/usr/bin/env bash
# AAATS Telegram self-heal telemetry snapshot (L3 observability) — READ-ONLY.
#
# WHY THIS EXISTS
# --------------
# The telegram self-heal's live state (bot health, RestartCount, watchdog
# liveness, token-hash baseline) lives only in `docker inspect` and
# /srv/aaats/state/ on the box — none of which reach origin/main (the box
# autopush snapshots runtime/ only). A dashboard that reads origin/main can't
# see it. This emitter writes a small JSON snapshot into the runtime repo so it
# rides the existing autopush to origin/main.
#
# STRICTLY READ-ONLY: it never recreates a container, never writes .env, and
# never touches the watchdog's control state. It only READS docker inspect +
# the watchdog's state files and WRITES one JSON file under runtime/. The
# verdict mirrors the watchdog's own logic for at-a-glance triage; the watchdog
# log remains authoritative.
#
# SCHEDULING: run every 5 min (own crontab line), same cadence as the watchdog.
#   */5 * * * * /home/aaats/bin/aaats-telegram-selfheal-snapshot.sh >> /home/aaats/aaats-telegram-selfheal-snapshot.log 2>&1
#
# Source-of-truth: scripts/box/aaats-telegram-selfheal-snapshot.sh in the AAATS repo.
# Deployed location on box: /home/aaats/bin/aaats-telegram-selfheal-snapshot.sh
set -uo pipefail

CONTAINER="${CONTAINER:-aaats-telegram-bot}"
STATE_DIR="${STATE_DIR:-/srv/aaats/state}"
WD_LOG="${WD_LOG:-/home/aaats/aaats-telegram-watchdog.log}"
OUT="${OUT:-/srv/aaats/runtime_repo/runtime/telegram_selfheal.json}"

HASH_FILE="$STATE_DIR/telegram_token.hash"
RC_FILE="$STATE_DIR/telegram_last_restartcount"
UNHEALTHY_MARKER="$STATE_DIR/telegram_unhealthy_since"
STARTING_MARKER="$STATE_DIR/telegram_starting_since"

# Mirror the watchdog's thresholds so the verdict matches its behavior.
STARTING_GRACE_SEC="${STARTING_GRACE_SEC:-600}"
# Watchdog cron is */5; >900s (3 missed ticks) means it has stopped ticking.
WATCHDOG_STALE_SEC="${WATCHDOG_STALE_SEC:-900}"

NOW=$(date -u +%s)
GEN=$(date -u +%FT%TZ)

# ── Bot inspect (handle container-absent) ────────────────────────────────────
if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  STATE=$(docker inspect --format '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "unknown")
  HEALTH=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || echo "none")
  RC=$(docker inspect --format '{{.RestartCount}}' "$CONTAINER" 2>/dev/null || echo "0")
  STARTED=$(docker inspect --format '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null || echo "")
  IMG=$(docker inspect --format '{{.Image}}' "$CONTAINER" 2>/dev/null | cut -c1-19)
  UPTIME=$(docker ps --filter "name=${CONTAINER}" --format '{{.Status}}' 2>/dev/null | head -1)
  [ -z "$UPTIME" ] && UPTIME="unknown"
  BOT_ABSENT=0
else
  STATE="absent"; HEALTH="none"; RC="0"; STARTED=""; IMG=""; UPTIME="absent"; BOT_ABSENT=1
fi

# ── Watchdog state files ─────────────────────────────────────────────────────
HASH_PRESENT=false; [ -f "$HASH_FILE" ] && HASH_PRESENT=true
UNH_PRESENT=false;  [ -f "$UNHEALTHY_MARKER" ] && UNH_PRESENT=true
START_PRESENT=false; [ -f "$STARTING_MARKER" ] && START_PRESENT=true

LAST_RC="null"
if [ -f "$RC_FILE" ]; then
  v=$(tr -dc '0-9-' < "$RC_FILE" 2>/dev/null)
  [ -n "$v" ] && LAST_RC="$v"
fi

STARTING_AGE=0
if [ "$START_PRESENT" = true ]; then
  s=$(tr -dc '0-9' < "$STARTING_MARKER" 2>/dev/null)
  [ -n "$s" ] && STARTING_AGE=$((NOW - s))
fi

CRON_PRESENT=false
crontab -l 2>/dev/null | grep -qF 'aaats-telegram-watchdog.sh' && CRON_PRESENT=true

# ── Watchdog liveness (mtime of the cron-appended log) ───────────────────────
if [ -f "$WD_LOG" ]; then
  WD_MTIME=$(stat -c %Y "$WD_LOG" 2>/dev/null || echo 0)
  WD_AGE=$((NOW - WD_MTIME))
  WD_TICK=$(date -u -d "@$WD_MTIME" +%FT%TZ 2>/dev/null || echo "")
else
  WD_AGE=-1; WD_TICK=""
fi

# ── Verdict (mirrors the watchdog's own logic) ───────────────────────────────
VERDICT="ok"
if [ "$BOT_ABSENT" -eq 1 ]; then
  VERDICT="bot_absent"
elif [ "$HEALTH" != "healthy" ] && [ "$LAST_RC" != "null" ] \
     && [ "$RC" -gt "$LAST_RC" ] 2>/dev/null; then
  VERDICT="crash_loop"
elif [ "$HEALTH" = "unhealthy" ]; then
  VERDICT="unhealthy"
elif [ "$HEALTH" = "starting" ] && [ "$LAST_RC" != "null" ] \
     && [ "$RC" -eq "$LAST_RC" ] 2>/dev/null && [ "$START_PRESENT" = true ] \
     && [ "$STARTING_AGE" -ge "$STARTING_GRACE_SEC" ]; then
  VERDICT="stuck_starting"
elif [ "$WD_AGE" -ge 0 ] && [ "$WD_AGE" -gt "$WATCHDOG_STALE_SEC" ]; then
  VERDICT="watchdog_stale"
fi

# ── JSON field formatting (numbers/null unquoted, strings quoted) ─────────────
if [ "$BOT_ABSENT" -eq 1 ]; then RC_JSON="null"; else RC_JSON="$RC"; fi
if [ -n "$STARTED" ]; then STARTED_JSON="\"$STARTED\""; else STARTED_JSON="null"; fi
if [ -n "$IMG" ]; then IMG_JSON="\"$IMG\""; else IMG_JSON="null"; fi
if [ -n "$WD_TICK" ]; then WD_TICK_JSON="\"$WD_TICK\""; else WD_TICK_JSON="null"; fi
if [ "$WD_AGE" -ge 0 ]; then WD_AGE_JSON="$WD_AGE"; else WD_AGE_JSON="null"; fi

# ── Atomic write (tmp + mv, same dir → autopush never sees a half file) ───────
mkdir -p "$(dirname "$OUT")" 2>/dev/null || true
TMP="$(mktemp "${OUT}.tmp.XXXXXX")" || { echo "mktemp failed" >&2; exit 1; }
cat > "$TMP" <<JSON
{
  "generated_utc": "$GEN",
  "bot": {
    "name": "$CONTAINER",
    "state": "$STATE",
    "health": "$HEALTH",
    "restart_count": $RC_JSON,
    "started_at": $STARTED_JSON,
    "uptime": "$UPTIME",
    "image": $IMG_JSON
  },
  "watchdog": {
    "last_tick_utc": $WD_TICK_JSON,
    "age_seconds": $WD_AGE_JSON,
    "hash_baseline_present": $HASH_PRESENT,
    "last_restartcount": $LAST_RC,
    "unhealthy_marker_present": $UNH_PRESENT,
    "starting_marker_present": $START_PRESENT,
    "cron_present": $CRON_PRESENT
  },
  "verdict": "$VERDICT"
}
JSON
mv -f "$TMP" "$OUT"
echo "[$GEN] wrote $OUT verdict=$VERDICT (state=$STATE health=$HEALTH rc=$RC wd_age=${WD_AGE}s)"
