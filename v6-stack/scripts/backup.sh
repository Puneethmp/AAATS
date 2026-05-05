#!/usr/bin/env bash
# AAATS v6 — Phase θ hourly backup
# Dumps Postgres + Redis from running containers, gzips, uploads to Cloudflare R2.
# Runs as the `aaats` user via systemd timer; rclone config at ~/.config/rclone/rclone.conf
# Retention:
#   local:  /srv/aaats/backups/  → 48 hourly snapshots (~2 days)
#   remote: r2:aaats-backups/    → 7 days of hourlies (rclone --min-age 7d delete)

set -euo pipefail

BACKUP_DIR=/srv/aaats/backups
LOG_FILE=/srv/aaats/logs/backup.log
SECRETS_DIR=/srv/aaats/secrets
RCLONE_REMOTE="${RCLONE_REMOTE:-r2:aaats-backups}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR" "$(dirname "$LOG_FILE")"

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG_FILE"; }
fail() { log "FATAL: $*"; exit 1; }

trap 'log "backup.sh exited with code $?"' EXIT

log "=== backup start ts=$TS ==="

# 1. Postgres dump (pg_dumpall captures roles + all DBs).
PG_FILE="$BACKUP_DIR/postgres-${TS}.sql.gz"
PG_PWD="$(cat "$SECRETS_DIR/postgres_password")"
PGPASSWORD="$PG_PWD" docker exec aaats-postgres \
  pg_dumpall -U aaats --clean --if-exists 2>>"$LOG_FILE" \
  | gzip -9 > "$PG_FILE"
PG_SIZE="$(stat -c %s "$PG_FILE")"
[ "$PG_SIZE" -gt 100 ] || fail "postgres dump too small: $PG_SIZE bytes"
log "postgres dump: $PG_FILE ($PG_SIZE bytes)"

# 2. Redis snapshot — trigger BGSAVE, wait for completion, copy dump.rdb out.
REDIS_PWD="$(cat "$SECRETS_DIR/redis_password")"
docker exec aaats-redis redis-cli -a "$REDIS_PWD" --no-auth-warning BGSAVE >>"$LOG_FILE" 2>&1 || true
# Wait until rdb_bgsave_in_progress flips to 0 (max 60s).
for _ in $(seq 1 30); do
  IN_PROGRESS="$(docker exec aaats-redis redis-cli -a "$REDIS_PWD" --no-auth-warning INFO persistence 2>/dev/null | grep -E '^rdb_bgsave_in_progress:' | tr -d '\r' | cut -d: -f2 || echo 0)"
  [ "$IN_PROGRESS" = "0" ] && break
  sleep 2
done
REDIS_FILE="$BACKUP_DIR/redis-${TS}.rdb.gz"
docker cp aaats-redis:/data/dump.rdb "$BACKUP_DIR/redis-${TS}.rdb"
gzip -9 "$BACKUP_DIR/redis-${TS}.rdb"
REDIS_SIZE="$(stat -c %s "$REDIS_FILE")"
[ "$REDIS_SIZE" -gt 100 ] || fail "redis dump too small: $REDIS_SIZE bytes"
log "redis dump:    $REDIS_FILE ($REDIS_SIZE bytes)"

# 3. Upload to R2.
log "uploading to $RCLONE_REMOTE …"
rclone copy "$PG_FILE"    "$RCLONE_REMOTE/postgres/" --quiet 2>>"$LOG_FILE"
rclone copy "$REDIS_FILE" "$RCLONE_REMOTE/redis/"    --quiet 2>>"$LOG_FILE"
log "upload complete"

# 4. Local retention — keep 48 hourlies (~2 days).
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'postgres-*.sql.gz' -mmin +2880 -delete 2>>"$LOG_FILE"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'redis-*.rdb.gz'   -mmin +2880 -delete 2>>"$LOG_FILE"

# 5. R2 retention — keep last 7 days (rclone deletes anything older).
rclone delete "$RCLONE_REMOTE/postgres/" --min-age 7d --quiet 2>>"$LOG_FILE" || true
rclone delete "$RCLONE_REMOTE/redis/"    --min-age 7d --quiet 2>>"$LOG_FILE" || true

log "=== backup complete ==="
