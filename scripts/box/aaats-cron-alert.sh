#!/usr/bin/env bash
# AAATS cron alert helper — fire Telegram directly from cron context.
# Bypasses aaats-telegram-bot container, which itself could be dead.
#
# Usage: aaats-cron-alert.sh "<message body>"
# Tokens are read from /home/aaats/aaats/.env (ALERTS__TELEGRAM_*).
#
# Source-of-truth: scripts/box/aaats-cron-alert.sh in the AAATS repo.
# Deployed location on box: /home/aaats/bin/aaats-cron-alert.sh
set -uo pipefail

ENV_FILE=/home/aaats/aaats/.env
MSG_BODY="${1:-(empty alert)}"
HOSTNAME_S="$(hostname)"
WHEN="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LOG=/home/aaats/aaats-autopush.log

log_line() { echo "[$WHEN] alert: $*" >> "$LOG"; }

if [ ! -f "$ENV_FILE" ]; then
  log_line "ENV_FILE missing — cannot fire alert"
  exit 1
fi

TOKEN="$(grep -E '^ALERTS__TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
CHAT="$(grep -E '^ALERTS__TELEGRAM_CHAT_ID='  "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"

if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
  log_line "TELEGRAM creds missing — cannot fire alert"
  exit 2
fi

MSG="AAATS CRON: ${MSG_BODY} at ${WHEN} on ${HOSTNAME_S}"

HTTP=$(curl -sS --max-time 15 -o /dev/null -w "%{http_code}" -X POST \
  "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=${CHAT}" \
  -d "text=${MSG}" 2>>"$LOG" || echo "000")

if [ "$HTTP" = "200" ]; then
  log_line "telegram alert sent (http=$HTTP): $MSG_BODY"
  exit 0
else
  log_line "telegram alert FAILED (http=$HTTP): $MSG_BODY"
  exit 3
fi
