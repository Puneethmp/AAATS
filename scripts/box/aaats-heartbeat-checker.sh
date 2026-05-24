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

# ─────────────────────────────────────────────────────────────────────
# Layer L10 (content-correctness 2026-05-24) — disk + repo-bloat +
# commit-rate watchdogs. Each fires via the same aaats-cron-alert
# helper with a distinct prefix. Each has its own cooldown state file
# so a disk-full event doesn't suppress a commit-rate alert.
# ─────────────────────────────────────────────────────────────────────

# Helper: fire an alert with a layer-specific cooldown (independent of
# the heartbeat cooldown above).
fire_layered_alert() {
  local layer="$1"
  local msg="$2"
  local state="/tmp/aaats-l10-${layer}-last-alert"
  local last=0
  [ -f "$state" ] && last=$(cat "$state" 2>/dev/null || echo 0)
  local since=$((NOW - last))
  if [ "$since" -lt "$COOLDOWN_SEC" ]; then
    echo "[$(date -u +%FT%TZ)] L10/${layer} suppressed (cooldown ${since}s): $msg"
    return 0
  fi
  "$ALERT" "L10/${layer}: $msg" || true
  echo "$NOW" > "$state"
  echo "[$(date -u +%FT%TZ)] L10/${layer} alert: $msg"
}

# ── L10/DISK ── /home disk usage > 85% ────────────────────────────────
DISK_PCT=$(df --output=pcent /home 2>/dev/null | tail -1 | tr -d '% ' || echo 0)
if [ -n "$DISK_PCT" ] && [ "$DISK_PCT" -gt 85 ]; then
  fire_layered_alert DISK "/home at ${DISK_PCT}% (>85% threshold)"
fi

# ── L10/REPO ── runtime_repo .git grew by >500MB in 24h ──────────────
REPO_DIR="${REPO_DIR:-/srv/aaats/runtime_repo}"
REPO_STATE="${REPO_STATE:-/tmp/aaats-l10-repo-prev-size}"
GIT_BYTES=$(du -sb "$REPO_DIR/.git" 2>/dev/null | awk '{print $1}' || echo 0)
if [ -n "$GIT_BYTES" ] && [ "$GIT_BYTES" -gt 0 ]; then
  if [ -f "$REPO_STATE" ]; then
    PREV_BYTES=$(awk '{print $1}' "$REPO_STATE" 2>/dev/null || echo 0)
    PREV_EPOCH=$(awk '{print $2}' "$REPO_STATE" 2>/dev/null || echo 0)
    AGE_HRS=$(( (NOW - PREV_EPOCH) / 3600 ))
    if [ "$AGE_HRS" -ge 24 ] && [ "$PREV_BYTES" -gt 0 ]; then
      GROWTH_BYTES=$((GIT_BYTES - PREV_BYTES))
      # 500MB = 524288000 bytes
      if [ "$GROWTH_BYTES" -gt 524288000 ]; then
        GROWTH_MB=$((GROWTH_BYTES / 1048576))
        fire_layered_alert REPO ".git grew ${GROWTH_MB}MB in ${AGE_HRS}h (>500MB threshold) — likely large blob committed by auto-cron; gc may be needed"
      fi
      # Refresh baseline after a comparison window completes (whether or
      # not it tripped) so the next 24h window starts fresh.
      echo "${GIT_BYTES} ${NOW}" > "$REPO_STATE"
    fi
  else
    # First run — capture baseline, no alert until next 24h window.
    echo "${GIT_BYTES} ${NOW}" > "$REPO_STATE"
  fi
fi

# ── L10/COMMIT_RATE ── auto-cron commits in 24h < 80 ─────────────────
# Expected ~96 = 24h * 4/h (cron tick every 15 min). Empty no-op ticks
# don't show up in git log because the autopush only commits on changes,
# so this is sensitive to "autopush ran but had nothing to commit" if
# that's the only failure pattern — but it's still a useful coarse
# liveness check that's independent of the heartbeat file.
if [ -d "$REPO_DIR/.git" ]; then
  COMMITS_24H=$(git -C "$REPO_DIR" log origin/main --since="24 hours ago" --grep="^auto:" --oneline 2>/dev/null | wc -l | tr -d ' ')
  if [ -n "$COMMITS_24H" ] && [ "$COMMITS_24H" -lt 80 ]; then
    fire_layered_alert COMMIT_RATE "auto-cron commits in last 24h = ${COMMITS_24H} (<80 expected); cron may be ticking but producing empty commits"
  fi
fi

exit 0
