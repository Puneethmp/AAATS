#!/usr/bin/env bash
# AAATS T3 dataset backup — nightly online snapshot of the OI collector DB.
#
# Additive and read-only against the live append-only collector: it uses the
# SQLite ONLINE backup API (via python3 stdlib, since the box has no guaranteed
# sqlite3 CLI), so it never locks or corrupts the concurrent hourly writer.
# Same-disk snapshots protect against corruption and accidental deletion.
# OFF-BOX durability (disk-loss protection) is the operator-run pull script
# tools/operator/backup_t3_pull.py — see docs/closeout/T3_PROTECTION.md.
#
# Source of truth: scripts/box/ in the repo. Deployed to /home/aaats/bin/.
# Cron: 30 2 * * *  (nightly 02:30 UTC).  Marker: AAATS-T3-BACKUP.
set -u
T3_DIR="/home/aaats/t3"
DB="${T3_DIR}/t3_positioning.db"
BK_DIR="${T3_DIR}/backups"
ALERT="/home/aaats/bin/aaats-cron-alert.sh"
DAY="$(date -u +%Y-%m-%d)"
OUT="${BK_DIR}/t3_positioning_${DAY}.db"

mkdir -p "${BK_DIR}"
if [ ! -f "${DB}" ]; then
  [ -x "${ALERT}" ] && bash "${ALERT}" "T3/BACKUP ERROR: source DB missing ${DB}"
  exit 1
fi

# Online backup via python3 stdlib (safe vs the append writer).
/usr/bin/python3 - "${DB}" "${OUT}" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
try:
    with dst:
        src.backup(dst)
finally:
    dst.close()
    src.close()
PY
rc=$?
if [ ${rc} -ne 0 ] || [ ! -s "${OUT}" ]; then
  [ -x "${ALERT}" ] && bash "${ALERT}" "T3/BACKUP ERROR: backup failed rc=${rc} for ${DAY}"
  rm -f "${OUT}"
  exit 1
fi

gzip -f "${OUT}"
if ! gzip -t "${OUT}.gz" 2>/dev/null; then
  [ -x "${ALERT}" ] && bash "${ALERT}" "T3/BACKUP ERROR: gzip integrity check failed ${DAY}"
  exit 1
fi

# Retention: keep the 14 most-recent dailies; keep every Sunday snapshot as a weekly.
cd "${BK_DIR}" || exit 0
ls -1t t3_positioning_*.db.gz 2>/dev/null | tail -n +15 | while read -r f; do
  d="${f#t3_positioning_}"; d="${d%.db.gz}"
  dow="$(date -u -d "${d}" +%u 2>/dev/null || echo 0)"
  [ "${dow}" != "7" ] && rm -f "${f}"
done

echo "[$(date -u +%FT%TZ)] t3-backup: wrote ${OUT}.gz ($(du -h "${OUT}.gz" 2>/dev/null | cut -f1))"
