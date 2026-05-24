#!/usr/bin/env bash
# AAATS heartbeat checker — fires Telegram if auto_cron_heartbeat.json
# hasn't been touched in >MAX_AGE_SEC (default 1200s = 20min).
#
# Detects "cron daemon died" (heartbeat never updates) — which is the
# blind spot that aaats-autopush-v3's own alerts can't cover.
#
# Scheduled by /etc/systemd/system/aaats-heartbeat-checker.timer every 5 min.
#
# Source-of-truth: scripts/box/aaats-heartbeat-checker.sh in the AAATS repo.
# Deployed location on box: /home/aaats/bin/aaats-heartbeat-checker.sh
set -uo pipefail

HEARTBEAT_FILE="${HEARTBEAT_FILE:-/srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json}"
MAX_AGE_SEC="${MAX_AGE_SEC:-1200}"
ALERT="${ALERT:-/home/aaats/bin/aaats-cron-alert.sh}"
STATE_FILE="${STATE_FILE:-/tmp/aaats-heartbeat-checker-last-alert}"
COOLDOWN_SEC="${COOLDOWN_SEC:-3600}"  # one alert per hour max

NOW=$(date -u +%s)

fire_alert_once() {
  local msg="$1"
  local last_alert=0
  [ -f "$STATE_FILE" ] && last_alert=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
  local since_last=$((NOW - last_alert))
  if [ "$since_last" -lt "$COOLDOWN_SEC" ]; then
    echo "[$(date -u +%FT%TZ)] suppressed (cooldown ${since_last}s < ${COOLDOWN_SEC}s): $msg"
    return 0
  fi
  "$ALERT" "watchdog: $msg" || true
  echo "$NOW" > "$STATE_FILE"
}

if [ ! -f "$HEARTBEAT_FILE" ]; then
  fire_alert_once "auto_cron_heartbeat.json missing — cron may have never run since restart"
  exit 1
fi

LAST_TICK_EPOCH=$(python3 - "$HEARTBEAT_FILE" <<'PY' 2>/dev/null || echo 0
import json, sys, time, calendar
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    t = d.get('last_tick', '')
    if not t: print(0); sys.exit(0)
    # calendar.timegm treats the parsed struct as UTC (mktime would treat it
    # as local — wrong on non-UTC hosts like the Contabo box, which runs CEST).
    print(int(calendar.timegm(time.strptime(t, '%Y-%m-%dT%H:%M:%SZ'))))
except Exception:
    print(0)
PY
)

if [ "$LAST_TICK_EPOCH" = "0" ]; then
  fire_alert_once "auto_cron_heartbeat.json unparseable"
  exit 2
fi

AGE=$((NOW - LAST_TICK_EPOCH))
if [ "$AGE" -gt "$MAX_AGE_SEC" ]; then
  AGE_MIN=$((AGE / 60))
  fire_alert_once "auto-cron heartbeat stale ${AGE_MIN}min (>${MAX_AGE_SEC}s threshold) — cron daemon may be dead"
  exit 3
fi

# fresh — clear any prior cooldown so next stale event alerts immediately
rm -f "$STATE_FILE" 2>/dev/null || true
echo "[$(date -u +%FT%TZ)] heartbeat fresh (age=${AGE}s, last=$(python3 -c "import json; print(json.load(open('$HEARTBEAT_FILE')).get('last_tick',''))"))"
exit 0
