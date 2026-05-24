#!/usr/bin/env bash
# AAATS one-shot diagnostics — prints a structured markdown report
# covering containers, cron, autopush log, git state, network, disk/mem,
# and the canonical heartbeat file.
#
# Usage:
#   ssh aaats@100.95.126.39 'bash /home/aaats/bin/aaats-diagnose.sh [--quick]'
#
# --quick: liveness-only sections (heartbeat age, autopush log tail, cron status).
#          Designed for completion in <5s.
#
# Source-of-truth: scripts/box/aaats-diagnose.sh in the AAATS repo.
# Deployed location on box: /home/aaats/bin/aaats-diagnose.sh
set -uo pipefail

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

HEARTBEAT_FILE=/srv/aaats/runtime_repo/runtime/auto_cron_heartbeat.json
AUTOPUSH_LOG=/home/aaats/aaats-autopush.log
REPO=/srv/aaats/runtime_repo

echo "# AAATS diagnose @ $(date -u +%FT%TZ) host=$(hostname)"
echo

echo "## Heartbeat"
if [ -f "$HEARTBEAT_FILE" ]; then
  cat "$HEARTBEAT_FILE"
  AGE_S=$(python3 - "$HEARTBEAT_FILE" 2>/dev/null <<'PY'
import json, sys, time, calendar
try:
    d = json.load(open(sys.argv[1]))
    t = d.get('last_tick','')
    # calendar.timegm interprets parsed struct as UTC; mktime would interpret
    # as local and miscount on non-UTC hosts (Contabo box runs CEST).
    print(int(time.time() - calendar.timegm(time.strptime(t,'%Y-%m-%dT%H:%M:%SZ'))))
except Exception:
    print(-1)
PY
)
  echo
  echo "_age: ${AGE_S}s_"
else
  echo "**MISSING:** $HEARTBEAT_FILE"
fi
echo

echo "## Autopush log (last 10)"
echo '```'
[ -f "$AUTOPUSH_LOG" ] && tail -10 "$AUTOPUSH_LOG" || echo "(missing $AUTOPUSH_LOG)"
echo '```'
echo

echo "## Cron service"
echo "- enabled: $(systemctl is-enabled cron 2>&1)"
echo "- active:  $(systemctl is-active cron 2>&1)"
echo

if [ "$QUICK" = "1" ]; then
  exit 0
fi

echo "## Crontab (aaats user)"
echo '```'
crontab -l 2>&1 | grep -v '^#' | grep -v '^$' || true
echo '```'
echo

echo "## systemd timers (AAATS)"
echo '```'
systemctl list-timers 'aaats-*' --no-pager 2>&1 | head -10
echo '```'
echo

echo "## Containers"
echo '```'
docker ps --format 'table {{.Names}}\t{{.Status}}' 2>&1
echo '```'
echo

echo "## runtime_repo git state"
if [ -d "$REPO/.git" ]; then
  cd "$REPO"
  echo "- branch: $(git rev-parse --abbrev-ref HEAD)"
  echo "- HEAD:   $(git log -1 --format='%h %s')"
  echo "- dry-run push:"
  echo '```'
  timeout 15 git push --dry-run origin main 2>&1 | head -5
  echo '```'
else
  echo "**MISSING:** $REPO/.git"
fi
echo

echo "## Network (github.com HTTPS)"
echo '```'
curl -sS --max-time 10 -o /dev/null -w "http=%{http_code} time=%{time_total}s\n" https://github.com 2>&1
echo '```'
echo

echo "## Disk + memory"
echo '```'
df -h / 2>&1 | head -3
echo
free -h | head -3
echo '```'
echo

echo "## paper-crypto tail (last 20)"
echo '```'
docker logs --tail 20 aaats-paper-crypto 2>&1 | tail -20
echo '```'
