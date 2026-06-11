#!/usr/bin/env bash
# AAATS weekly report — the operator's ONLY required contact surface in
# maintenance mode (steady-state handoff, 2026-06-11).
#
# Generates REPORTS/week_NN.md (honest net-of-cost ledger + no-trade
# baseline via tools/reports/weekly_report.py) and appends the ops sections
# the maintenance contract requires: open-book status, OI collector health,
# health-check anomalies. The finished report is dropped into the runtime
# repo so the next auto-cron push publishes it to origin/main — read it on
# GitHub, no SSH needed.
#
# Source of truth: scripts/box/ in the repo. Deployed to /home/aaats/bin/.
# Cron: 10 6 * * 1 (Mondays 06:10 UTC). Marker: AAATS-WEEKLY-REPORT.
# No Telegram: the weekly report is a pull surface, not an alert.
set -u

REPO=/home/aaats/aaats
RUNTIME_REPO=/srv/aaats/runtime_repo
DB="${REPO}/data/paper_trades.db"        # host side of the data/ bind mount
T3_DB=/home/aaats/t3/t3_positioning.db
OUT_DIR="${RUNTIME_REPO}/runtime/REPORTS"
WEEK=$(date -u +%V)
SINCE=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S+00:00)
TMP=$(mktemp -d)

mkdir -p "${OUT_DIR}"
cd "${REPO}"

# 1. Honest-PnL core (net-of-cost repricing + no-trade baseline).
/usr/bin/python3 tools/reports/weekly_report.py \
  --db "${DB}" --since "${SINCE}" --week "${WEEK}" --out "${TMP}" \
  || echo "weekly_report.py FAILED rc=$? (continuing with ops sections)" > "${TMP}/week_${WEEK}.md"
REPORT="${TMP}/week_${WEEK}.md"
[ -f "${REPORT}" ] || REPORT=$(ls "${TMP}"/week_*.md 2>/dev/null | head -1)
[ -n "${REPORT}" ] || { REPORT="${TMP}/week_${WEEK}.md"; echo "# week ${WEEK} (generator produced nothing)" > "${REPORT}"; }

# 2. Ops appendix.
{
  echo
  echo "## Open book (maintenance contract: should be EMPTY)"
  echo '```'
  for f in altcoin_reversion_state bollinger_range_state stat_arb_state; do
    printf '%s: ' "$f"; cat "${REPO}/data/${f}.json" 2>/dev/null || echo MISSING; echo
  done
  echo '```'
  echo
  echo "## OI collector health (T3 — the only live research thread, usable ~2027)"
  echo '```'
  /usr/bin/python3 - "${T3_DB}" <<'PY'
import sqlite3, sys, datetime, os
db = sys.argv[1]
try:
    con = sqlite3.connect(db)
    n, last = con.execute("SELECT COUNT(*), MAX(ts_utc) FROM oi_snapshots").fetchone()
    wk = con.execute("SELECT COUNT(*) FROM oi_snapshots WHERE ts_utc >= datetime('now', '-7 days')").fetchone()[0]
    print(f"rows_total={n}  rows_last_7d={wk}  newest={last}")
    rows = [r[0] for r in con.execute(
        "SELECT DISTINCT substr(ts_utc, 1, 13) FROM oi_snapshots WHERE ts_utc >= datetime('now', '-7 days') ORDER BY 1")]
    print(f"distinct collection hours last 7d: {len(rows)} (expect ~168; gaps if fewer)")
except Exception as exc:
    print(f"OI DB unreadable: {exc}")
print(f"db_size_bytes={os.path.getsize(db) if os.path.exists(db) else 'MISSING'}")
PY
  df -h /home | tail -1 | awk '{print "disk /home: used "$3" of "$2" ("$5")"}'
  echo '```'
  echo
  echo "## Health anomalies (last 7 days)"
  echo '```'
  docker inspect aaats-paper-crypto --format 'paper-crypto: health={{.State.Health.Status}} restarts={{.RestartCount}} started={{.State.StartedAt}}' 2>/dev/null
  echo "heartbeat-checker alerts (non-OK lines, last 7d):"
  grep -v "heartbeat fresh" /home/aaats/aaats-heartbeat-checker.log 2>/dev/null | tail -10 || echo "(none)"
  echo "t3-watchdog alerts (non-OK lines):"
  grep -v "OK age" /home/aaats/t3/watchdog.log 2>/dev/null | tail -5 || echo "(none)"
  echo '```'
  echo
  echo "_Generated $(date -u +%FT%TZ) by aaats-weekly-report.sh (cron, Mondays 06:10Z)._"
} >> "${REPORT}"

# 3. Publish via the runtime repo (next autopush commits runtime/).
cp "${REPORT}" "${OUT_DIR}/$(basename "${REPORT}")"
echo "[$(date -u +%FT%TZ)] weekly report written: ${OUT_DIR}/$(basename "${REPORT}")"
rm -rf "${TMP}"
