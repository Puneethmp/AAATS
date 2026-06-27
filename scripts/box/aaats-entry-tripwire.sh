#!/usr/bin/env bash
# AAATS entry tripwire — maintenance-mode alert condition (a).
#
# The research bed is demoted to no-trade (ENTRIES_DISABLED, 2026-06-10):
# an entry event is IMPOSSIBLE by design. If one ever appears in the ledger,
# something has bypassed the demotion gates (bad deploy, manual flip, code
# regression) and the operator must know immediately. This script is the
# tripwire: it scans paper_trades.db for entry-type rows newer than a
# watermark and fires one Telegram alert per occurrence batch.
#
# Entry-type row = action='BUY' whose note is NOT a C1 pair-close leg
# (stat_arb EXIT writes a BUY row for the short leg — that is an exit).
# SELL rows are always exits and never alert.
#
# Source of truth: scripts/box/ in the repo. Deployed to /home/aaats/bin/.
# Cron: */30 * * * *  Marker: AAATS-ENTRY-TRIPWIRE.
set -u

WATERMARK="/home/aaats/.entry_tripwire_watermark"
ALERT="/home/aaats/bin/aaats-cron-alert.sh"
CONTAINER="aaats-paper-crypto"

# ── Paper-window guard (2026-06-27) ──────────────────────────────────────────
# During an operator-authorized, time-boxed PAPER-ONLY entry window, paper
# entries are EXPECTED and must NOT page. If the deadline file exists and its
# epoch is in the future, suppress (the window auto-reverts at the deadline; the
# revert job then advances the watermark so window entries never flood-alert).
# Fail-safe: if the file is absent or malformed, fall through to NORMAL alerting.
# See docs/decisions/2026-06-27_paper_only_entry_resume.md.
WINDOW_DEADLINE_FILE="/srv/aaats/state/paper_entry_window_deadline"
if [ -f "${WINDOW_DEADLINE_FILE}" ]; then
  _deadline=$(tr -dc '0-9' < "${WINDOW_DEADLINE_FILE}" 2>/dev/null)
  _now=$(date -u +%s)
  if [ -n "${_deadline}" ] && [ "${_now}" -lt "${_deadline}" ] 2>/dev/null; then
    echo "[$(date -u +%FT%TZ)] tripwire: paper window active (until $(date -u -d "@${_deadline}" +%FT%TZ 2>/dev/null)) — suppressing"
    exit 0
  fi
fi

# Initialize watermark to the demotion deploy moment on first run.
[ -f "${WATERMARK}" ] || echo "2026-06-10T17:12:00+00:00" > "${WATERMARK}"
SINCE=$(cat "${WATERMARK}")

# Container down is NOT this tripwire's job (L3 heartbeat-checker owns
# liveness). Exit quietly so cron mail stays silent.
docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null | grep -q true || {
  echo "[$(date -u +%FT%TZ)] tripwire: container not running — skipping (L3 owns this)"
  exit 0
}

RESULT=$(docker exec "${CONTAINER}" python -c "
import sqlite3
con = sqlite3.connect('/app/data/paper_trades.db')
rows = con.execute(
    \"SELECT timestamp, strategy, symbol FROM paper_trades \"
    \"WHERE action='BUY' AND note NOT LIKE 'stat_arb EXIT%' AND timestamp > ? \"
    \"ORDER BY timestamp\", ('${SINCE}',)).fetchall()
print(len(rows))
for r in rows[:5]:
    print('|'.join(str(x) for x in r))
" 2>/dev/null) || {
  echo "[$(date -u +%FT%TZ)] tripwire: docker exec failed — skipping"
  exit 0
}

COUNT=$(echo "${RESULT}" | head -1)
if [ "${COUNT:-0}" -gt 0 ] 2>/dev/null; then
  DETAIL=$(echo "${RESULT}" | tail -n +2 | head -5 | tr '\n' ' ')
  "${ALERT}" "AAATS ENTRY TRIPWIRE: ${COUNT} entry row(s) in paper_trades.db after ${SINCE} — entries are supposed to be IMPOSSIBLE (research-bed demotion 2026-06-10). Rows: ${DETAIL}. Investigate live_paper_runner ENTRIES_DISABLED + strategy gates before anything else."
  # Advance watermark so the same rows alert once; new rows re-trigger.
  docker exec "${CONTAINER}" python -c "
import sqlite3
con = sqlite3.connect('/app/data/paper_trades.db')
print(con.execute(\"SELECT MAX(timestamp) FROM paper_trades WHERE action='BUY' AND note NOT LIKE 'stat_arb EXIT%'\").fetchone()[0])
" > "${WATERMARK}" 2>/dev/null
  echo "[$(date -u +%FT%TZ)] tripwire: ALERT FIRED count=${COUNT}"
else
  echo "[$(date -u +%FT%TZ)] tripwire: clean (no entries after ${SINCE})"
fi
