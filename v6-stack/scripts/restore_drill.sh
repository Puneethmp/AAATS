#!/usr/bin/env bash
# AAATS v6 — Phase θ restore drill
# Pulls the latest postgres backup from R2, restores it into a throwaway
# postgres container, and verifies row counts match the live container.
# Cleans up after itself. Logs to /srv/aaats/logs/restore_drill.log.
# Run quarterly (or on demand) per RR R-21 mitigation.

set -euo pipefail

LOG=/srv/aaats/logs/restore_drill.log
TMPDIR="$(mktemp -d)"
RCLONE_REMOTE="${RCLONE_REMOTE:-r2:aaats-backups}"
TEST_NET=aaats-restore-net
TEST_CONTAINER=aaats-restore-test

cleanup() {
  rm -rf "$TMPDIR"
  docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$TEST_NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT

mkdir -p "$(dirname "$LOG")"
log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }

log "=== restore drill start ==="

# 1. Pick the latest postgres backup in R2.
LATEST="$(rclone lsf "$RCLONE_REMOTE/postgres/" 2>>"$LOG" | sort -r | head -1 || true)"
[ -z "$LATEST" ] && { log "FAIL: no postgres backups in $RCLONE_REMOTE/postgres/"; exit 2; }
log "latest backup: $LATEST"

rclone copy "$RCLONE_REMOTE/postgres/$LATEST" "$TMPDIR/" --quiet 2>>"$LOG"
log "downloaded → $TMPDIR/$LATEST"

# 2. Spin up an isolated postgres container.
TEST_PWD="$(openssl rand -base64 18 | tr -d '\n=/+' | head -c 24)"
docker network create "$TEST_NET" >/dev/null 2>>"$LOG" || true
docker run -d \
  --name "$TEST_CONTAINER" \
  --network "$TEST_NET" \
  -e POSTGRES_PASSWORD="$TEST_PWD" \
  -e POSTGRES_USER=aaats \
  -e POSTGRES_DB=postgres \
  postgres:16-alpine >/dev/null
log "throwaway container started"

# Wait for it to accept connections.
for _ in $(seq 1 30); do
  docker exec "$TEST_CONTAINER" pg_isready -U aaats >/dev/null 2>&1 && break
  sleep 1
done

# 3. Restore the dump.
log "restoring dump …"
gunzip -c "$TMPDIR/$LATEST" | docker exec -i "$TEST_CONTAINER" psql -U aaats -d postgres >>"$LOG" 2>&1
log "restore complete"

# 4. Verification — compare cp3_smoke_test row counts.
LIVE_PWD="$(cat /srv/aaats/secrets/postgres_password)"
LIVE_COUNT="$(docker run --rm --network aaats -e PGPASSWORD="$LIVE_PWD" postgres:16-alpine \
  psql -h aaats-postgres -U aaats -d aaats -tAc 'SELECT count(*) FROM aaats.cp3_smoke_test' 2>/dev/null \
  | tr -d ' \r\n' || echo 0)"

RESTORED_COUNT="$(docker exec "$TEST_CONTAINER" \
  psql -U aaats -d aaats -tAc 'SELECT count(*) FROM aaats.cp3_smoke_test' 2>/dev/null \
  | tr -d ' \r\n' || echo 0)"

log "live aaats.cp3_smoke_test rows:     $LIVE_COUNT"
log "restored aaats.cp3_smoke_test rows: $RESTORED_COUNT"

if [ "$LIVE_COUNT" = "$RESTORED_COUNT" ]; then
  log "PASS: row counts match"
  RTO_END="$(date -u +%FT%TZ)"
  log "drill duration: started at script invocation; finished $RTO_END"
  exit 0
fi

log "FAIL: row counts differ"
exit 1
