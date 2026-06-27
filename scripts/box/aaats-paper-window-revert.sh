#!/usr/bin/env bash
# AAATS paper-window auto-revert (2026-06-27) — returns the research bed to
# entries-disabled automatically at the end of the operator-authorized,
# time-boxed PAPER-ONLY observation window. Cron deadline-guard (atd is
# inactive on the box, so `at` is not used).
#
# MECHANISM
#   Reads the deadline file (epoch). Before the deadline: no-op. At/after it:
#     1. restore the 4 ENTRIES_DISABLED=True source files from the backup,
#     2. rebuild ONLY aaats-paper-crypto (--no-deps --build),
#     3. verify the rebuilt image has ENTRIES_DISABLED=True in all 4 files,
#     4. on success: advance the entry-tripwire watermark (so window entries
#        don't flood-alert), remove the deadline file (re-arms the tripwire
#        window-guard), remove this cron line, and Telegram a "window closed".
#     5. on rebuild/verify FAILURE: set the operator halt for crypto as an
#        immediate flat-gate (no rebuild needed) and Telegram a loud failure
#        alert; leave the deadline + cron so it retries next tick.
#
# This is the safety backstop. The system returns to flat/entries-disabled even
# if the operator forgets. NOT a strategy reopen.
# Decision: docs/decisions/2026-06-27_paper_only_entry_resume.md
# Source-of-truth: scripts/box/ in the repo. Deployed to /home/aaats/bin/.
# Cron: */15 * * * *  Marker: AAATS-PAPER-WINDOW-REVERT.
set -uo pipefail

REPO="/home/aaats/aaats"
COMPOSE="${REPO}/deployment/docker-compose.yml"
CONTAINER="aaats-paper-crypto"
ALERT="/home/aaats/bin/aaats-cron-alert.sh"
STATE_DIR="/srv/aaats/state"
DEADLINE_FILE="${STATE_DIR}/paper_entry_window_deadline"
BACKUP_DIR="${STATE_DIR}/paper_entry_window_revert"
WATERMARK="/home/aaats/.entry_tripwire_watermark"
FILES="live_paper_runner.py stat_arb.py altcoin_reversion.py bollinger_range.py"

WHEN=$(date -u +%FT%TZ)
log() { echo "[${WHEN}] paper-window-revert: $*"; }

# ── Deadline gate ────────────────────────────────────────────────────────────
[ -f "${DEADLINE_FILE}" ] || { log "no deadline file — nothing to do"; exit 0; }
DEADLINE=$(tr -dc '0-9' < "${DEADLINE_FILE}" 2>/dev/null)
NOW=$(date -u +%s)
if [ -z "${DEADLINE}" ]; then
  log "deadline file malformed — alerting, leaving as-is for operator"
  "${ALERT}" "paper-window-revert: deadline file ${DEADLINE_FILE} is malformed — auto-revert cannot compute the window end. Manually revert per .rollback/2026-06-27_paper_entry_resume/MANIFEST.txt." || true
  exit 1
fi
if [ "${NOW}" -lt "${DEADLINE}" ]; then
  log "window still open (until $(date -u -d "@${DEADLINE}" +%FT%TZ 2>/dev/null)) — no action"
  exit 0
fi

log "DEADLINE reached — reverting paper crypto to entries-disabled"

# ── 1. restore the True source files ─────────────────────────────────────────
if [ -d "${BACKUP_DIR}" ]; then
  for f in ${FILES}; do
    [ -f "${BACKUP_DIR}/${f}" ] && cp -f "${BACKUP_DIR}/${f}" "${REPO}/trading/${f}"
  done
  log "restored True source files from ${BACKUP_DIR}"
else
  # Fallback: sed the flag back in place if the backup is missing.
  for f in ${FILES}; do
    sed -i 's/^ENTRIES_DISABLED = False/ENTRIES_DISABLED = True/' "${REPO}/trading/${f}" 2>/dev/null || true
  done
  log "backup dir missing — sed-reverted flags in place"
fi

# ── 2. rebuild only the paper container ──────────────────────────────────────
cd "${REPO}" || { "${ALERT}" "paper-window-revert: cannot cd ${REPO} — MANUAL revert needed"; exit 1; }
docker compose -p deployment -f "${COMPOSE}" up -d --no-deps --build "${CONTAINER}" >/dev/null 2>&1
sleep 8

# ── 3. verify the rebuilt image has all 4 flags True ─────────────────────────
OKCOUNT=$(docker exec "${CONTAINER}" sh -c \
  "grep -h '^ENTRIES_DISABLED = ' trading/live_paper_runner.py trading/stat_arb.py trading/altcoin_reversion.py trading/bollinger_range.py 2>/dev/null | grep -c 'True'" \
  2>/dev/null | tr -dc '0-9')

if [ "${OKCOUNT:-0}" = "4" ]; then
  # ── 4. success: re-arm tripwire + clean up ─────────────────────────────────
  docker exec "${CONTAINER}" python -c "
import sqlite3
c=sqlite3.connect('/app/data/paper_trades.db')
r=c.execute(\"SELECT MAX(timestamp) FROM paper_trades WHERE action='BUY' AND note NOT LIKE 'stat_arb EXIT%'\").fetchone()[0]
print(r or '')" > "${WATERMARK}" 2>/dev/null || true
  rm -f "${DEADLINE_FILE}"
  crontab -l 2>/dev/null | grep -v 'AAATS-PAPER-WINDOW-REVERT' | crontab - 2>/dev/null || true
  log "REVERT OK — entries disabled (4/4 flags True), tripwire re-armed, cron removed"
  "${ALERT}" "AAATS paper window CLOSED: PAPER-ONLY entry resume reverted automatically — entries disabled again, book winding down to flat, entry tripwire re-armed. (Observation only; NO-GO verdict unchanged.) Restore the repo ENTRIES_DISABLED flags to True at your convenience." || true
  exit 0
fi

# ── 5. failure: halt fallback (no rebuild) + loud alert, retry next tick ──────
log "REVERT VERIFY FAILED (flags True count=${OKCOUNT:-0}/4) — applying halt fallback"
echo '{"us":true,"india":true,"crypto":true}' | docker exec -i "${CONTAINER}" sh -c 'cat > /app/data/halt_state.json' 2>/dev/null || true
"${ALERT}" "AAATS paper-window-revert FAILED to rebuild/verify (flags True=${OKCOUNT:-0}/4). Applied operator HALT crypto=true as an immediate flat-gate (no new entries). MANUAL action needed: see .rollback/2026-06-27_paper_entry_resume/MANIFEST.txt. Will retry next */15 tick." || true
exit 1
