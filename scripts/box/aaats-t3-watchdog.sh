#!/usr/bin/env bash
# AAATS T3 collector watchdog — detects a SILENT collection gap.
#
# The collector self-alerts only on disk>85% and on a tick that returns 0 OI.
# A tick that NEVER RUNS (cron stopped, box rebooted, daemon hung) is otherwise
# completely silent — and a gap >30 days is unrecoverable (Binance serves only
# ~30d of OI history). This watchdog fires one cooldown-guarded alert when the
# newest OI row is older than the staleness limit. Read-only against the DB.
#
# Source of truth: scripts/box/ in the repo. Deployed to /home/aaats/bin/.
# Cron: */30 * * * *  (every 30 min).  Marker: AAATS-T3-WATCHDOG.
set -u
T3_DIR="/home/aaats/t3"
DB="${T3_DIR}/t3_positioning.db"
ALERT="/home/aaats/bin/aaats-cron-alert.sh"
STAMP="${T3_DIR}/.t3_stale_alert_stamp"
LIMIT_S=7200      # 2h: collector is hourly, so >2h since the newest row = a missed tick
COOLDOWN_S=21600  # one stale alert per 6h

now=$(date -u +%s)
last_iso=$(/usr/bin/python3 - "${DB}" <<'PY'
import sqlite3, sys
try:
    c = sqlite3.connect(sys.argv[1])
    r = c.execute("select max(ts_utc) from oi_snapshots").fetchone()[0]
    print(r or "")
except Exception:
    print("")
PY
)

if [ -z "${last_iso}" ]; then
  age=999999
else
  last_s=$(date -u -d "${last_iso}" +%s 2>/dev/null || echo 0)
  age=$(( now - last_s ))
fi

if [ "${age}" -lt "${LIMIT_S}" ]; then
  echo "[$(date -u +%FT%TZ)] t3-watchdog: OK age=${age}s last=${last_iso:-NONE}"
  exit 0
fi

last_alert=0
[ -f "${STAMP}" ] && last_alert=$(cat "${STAMP}" 2>/dev/null || echo 0)
if [ $(( now - last_alert )) -ge "${COOLDOWN_S}" ]; then
  [ -x "${ALERT}" ] && bash "${ALERT}" \
    "T3/STALE collector: newest OI row is ${age}s old (>${LIMIT_S}s). Last=${last_iso:-NONE}. Hourly cron may be dead — a >30d gap is UNRECOVERABLE."
  echo "${now}" > "${STAMP}"
fi
echo "[$(date -u +%FT%TZ)] t3-watchdog: STALE age=${age}s last=${last_iso:-NONE}"
