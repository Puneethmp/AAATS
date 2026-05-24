#!/usr/bin/env bash
# AAATS auto-push v3 — heartbeat-first, retry, external alert on failure.
#
# Hardens v2 by:
#   1. Writing a pre-push heartbeat file so liveness can distinguish
#      "cron tick happened" from "cron tick happened AND push succeeded".
#   2. Retrying `git push` 3x with linear backoff (30s/60s/90s).
#   3. Firing a Telegram alert via aaats-cron-alert.sh on terminal failure.
#
# Source-of-truth: scripts/box/aaats-autopush-v3.sh in the AAATS repo.
# Deployed location on box: /home/aaats/bin/aaats-autopush.sh
# Cron entry: */15 * * * * /home/aaats/bin/aaats-autopush.sh
set -uo pipefail

REPO=/srv/aaats/runtime_repo
LOG=/home/aaats/aaats-autopush.log
HEARTBEAT_FILE=/srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json
RUNTIME_DIR="$REPO/runtime"
LOCKFILE=/tmp/aaats-autopush.lock
ALERT=/home/aaats/bin/aaats-cron-alert.sh

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$LOG"; }

# Heartbeat writer — uses python3 (always available; jq is not guaranteed).
write_heartbeat() {
  local status="$1"
  local extra="${2:-}"
  mkdir -p "$(dirname "$HEARTBEAT_FILE")"
  python3 - "$HEARTBEAT_FILE" "$status" "$extra" <<'PY' || true
import json, os, sys, time, socket
path, status, extra = sys.argv[1], sys.argv[2], sys.argv[3]
now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
prev = {}
try:
    with open(path) as f:
        prev = json.load(f)
except Exception:
    prev = {}
prev['last_tick'] = now
prev['host'] = socket.gethostname()
prev['status'] = status
if status == 'ok':
    prev['last_push'] = now
    prev.pop('last_fail', None)
elif status in ('push_failed', 'fetch_failed'):
    prev['last_fail'] = now
if extra:
    prev['note'] = extra
tmp = path + '.tmp'
with open(tmp, 'w') as f:
    json.dump(prev, f, indent=2)
os.replace(tmp, path)
PY
}

# Single-instance lock — prevent overlapping cron runs.
exec 9>"$LOCKFILE"
flock -n 9 || { log "skip — previous run still in progress"; exit 0; }

# 1. Write started heartbeat FIRST — independent of push outcome.
write_heartbeat "started"
log "=== cron tick ==="

# Skip if repo not initialized (deploy key not yet on GitHub).
if [ ! -d "$REPO/.git" ]; then
  mkdir -p "$REPO" && cd "$REPO"
  if timeout 30 git clone git@github.com:Puneethmp/AAATS.git . 2>>"$LOG"; then
    git config user.email "aaats-deploy@contabo"
    git config user.name "AAATS Auto-Deploy"
    log "first clone OK"
  else
    log "SKIP — deploy key not yet on GitHub"
    write_heartbeat "no_repo"
    exit 0
  fi
fi

cd "$REPO"

# 2. Fetch + hard-reset to absorb workstation commits.
if ! timeout 30 git fetch origin main --quiet 2>>"$LOG"; then
  log "fetch failed"
  write_heartbeat "fetch_failed"
  "$ALERT" "fetch from origin failed" 2>>"$LOG" || true
  exit 2
fi
git reset --hard origin/main --quiet 2>>"$LOG" || true
mkdir -p "$RUNTIME_DIR"

# 3. Snapshot runtime state from engine container (read-only docker cp).
timeout 15 docker cp aaats-engine:/app/data/paper_trades.db      "$RUNTIME_DIR/paper_trades.db"      2>>"$LOG" || log "cp paper_trades.db failed"
timeout 15 docker cp aaats-engine:/app/data/paper_positions.json "$RUNTIME_DIR/paper_positions.json" 2>>"$LOG" || true
timeout 15 docker cp aaats-engine:/app/data/paper_portfolio.json "$RUNTIME_DIR/paper_portfolio.json" 2>>"$LOG" || true
timeout 15 docker cp aaats-engine:/app/data/stat_arb_state.json  "$RUNTIME_DIR/stat_arb_state.json"  2>>"$LOG" || true
timeout 10 docker logs --tail 500 aaats-engine 2>&1 | tail -500 > "$RUNTIME_DIR/engine.log" || true

if [ -f "$RUNTIME_DIR/paper_trades.db" ]; then
  python3 - "$RUNTIME_DIR/paper_trades.db" > "$RUNTIME_DIR/paper_trades.csv" 2>>"$LOG" << 'PY' || true
import sqlite3, csv, sys
conn = sqlite3.connect(sys.argv[1])
cur = conn.execute("SELECT * FROM paper_trades ORDER BY timestamp")
cols = [d[0] for d in cur.description]
w = csv.writer(sys.stdout); w.writerow(cols)
for row in cur.fetchall(): w.writerow(row)
PY
fi

{
  echo "# AAATS runtime snapshot"
  echo
  echo "Last update: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## Container heartbeats"
  timeout 10 docker ps --format '- {{.Names}}: {{.Status}}' | grep aaats- | sort
} > "$RUNTIME_DIR/STATUS.md"

# 4. Stage + commit if dirty.
git add runtime/
if git diff --cached --quiet; then
  log "no changes to commit"
  write_heartbeat "ok" "no-op tick"
  exit 0
fi
MSG="auto: $(date -u +%Y-%m-%dT%H:%M:%SZ) trades + logs"
git commit -m "$MSG" --quiet || true

# 5. Push with 3x linear backoff retry.
PUSH_OK=0
for attempt in 1 2 3; do
  if timeout 30 git push origin main --quiet 2>>"$LOG"; then
    log "pushed: $MSG (attempt $attempt)"
    PUSH_OK=1
    break
  fi
  SLEEP_FOR=$((attempt * 30))
  log "push FAILED attempt $attempt — sleeping ${SLEEP_FOR}s before retry"
  # On non-final attempt, ensure we refetch in case the failure was a non-ff
  if [ "$attempt" -lt 3 ]; then
    sleep "$SLEEP_FOR"
    timeout 30 git pull --rebase origin main --quiet 2>>"$LOG" || true
  fi
done

if [ "$PUSH_OK" = "1" ]; then
  write_heartbeat "ok"
  exit 0
fi

# 6. All retries failed — local alert + mark heartbeat broken.
log "push FAILED after 3 attempts — firing alert"
write_heartbeat "push_failed" "3 retries exhausted"
"$ALERT" "auto-push failed 3x after retries" 2>>"$LOG" || true
exit 3
