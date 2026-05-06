#!/bin/bash
# ============================================================
# AAATS AUTODRIVER v2.0 — Auto-chains Claude Code sessions
# Updated: April 2026
#
# Changes from v1.0:
#   - BLOCKED status no longer exits — it logs a warning and continues
#   - India pipeline is built with mocks — no real API needed
#   - SESSION_STATE.md BLOCKED lines only stop the build if
#     STOP_ON_BLOCKED=true is set in environment
#   - Better state-change detection
#   - Max sessions configurable via MAX_SESSIONS env var
#
# Drop into AAATS project root and run:
#   chmod +x autodriver.sh && bash autodriver.sh
#
# To stop on blocks (old behavior):
#   STOP_ON_BLOCKED=true bash autodriver.sh
# ============================================================

PROJECT_DIR="$(pwd)"
LOG_FILE="$PROJECT_DIR/.claude/autodriver.log"
STATE_FILE="$PROJECT_DIR/SESSION_STATE.md"
MAX_SESSIONS="${MAX_SESSIONS:-50}"
STOP_ON_BLOCKED="${STOP_ON_BLOCKED:-false}"
SESSION_COUNT=0

mkdir -p "$PROJECT_DIR/.claude"

log() {
  echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ── Pre-flight checks ────────────────────────────────────────
if ! command -v claude &>/dev/null; then
  echo "ERROR: claude CLI not found."
  echo "Install: npm install -g @anthropic-ai/claude-code"
  exit 1
fi

if [ ! -f "$PROJECT_DIR/MASTER_AUTODRIVER.md" ]; then
  echo "ERROR: MASTER_AUTODRIVER.md not found in $PROJECT_DIR"
  exit 1
fi

if [ ! -f "$STATE_FILE" ]; then
  echo "ERROR: SESSION_STATE.md not found in $PROJECT_DIR"
  exit 1
fi

log "═══════════════════════════════════════════════"
log "AAATS AUTODRIVER v2.0 STARTED"
log "Project: $PROJECT_DIR"
log "Max sessions: $MAX_SESSIONS"
log "Stop on blocked: $STOP_ON_BLOCKED"
log "═══════════════════════════════════════════════"

# ── Main loop ────────────────────────────────────────────────
while [ $SESSION_COUNT -lt $MAX_SESSIONS ]; do
  SESSION_COUNT=$((SESSION_COUNT + 1))

  # Read current state before session
  STATE_BEFORE=$(tail -1 "$STATE_FILE" 2>/dev/null || echo "")

  # Check ALL_DONE before launching Claude
  if echo "$STATE_BEFORE" | grep -q "NEXT: ALL_DONE"; then
    log "═══════════════════════════════════════════════"
    log "✅ ALL MODULES BUILT — BUILD COMPLETE"
    log "═══════════════════════════════════════════════"
    exit 0
  fi

  # Extract next module from state
  NEXT_MODULE=$(echo "$STATE_BEFORE" | grep -oP 'NEXT: \K[^|]+' | tr -d ' ')

  # Handle BLOCKED state
  if echo "$STATE_BEFORE" | grep -q "STATUS: BLOCKED"; then
    BLOCK_REASON=$(echo "$STATE_BEFORE" | grep -oP 'REASON: \K.*' | tr -d '\n')

    if [ "$STOP_ON_BLOCKED" = "true" ]; then
      log "═══════════════════════════════════════════════"
      log "⚠️  BUILD PAUSED — STOP_ON_BLOCKED=true"
      log "Reason: $BLOCK_REASON"
      log "Re-run once dependency resolved."
      log "═══════════════════════════════════════════════"
      exit 0
    else
      # v2.0 behavior: log the block, skip, continue to next module
      log "⚠️  State shows BLOCKED: $BLOCK_REASON"
      log "   STOP_ON_BLOCKED is false — prompting Claude to build next unblocked module."
      NEXT_MODULE="AUTO_DETECT"
    fi
  fi

  # Handle HOTFIX state
  if echo "$STATE_BEFORE" | grep -q "^HOTFIX:"; then
    HOTFIX_LINE=$(cat "$STATE_FILE")
    log "▶ HOTFIX SESSION $SESSION_COUNT"
    PROMPT="Read SESSION_STATE.md first. It contains a HOTFIX instruction.
Read MASTER_AUTODRIVER.md HOTFIX MODE section and follow it exactly for this hotfix.
Do not touch any other module. After the hotfix is complete and tests pass, update SESSION_STATE.md, README.md, and AAATS_MASTER_BLUEPRINT.md change log, then stop."
  else
    log "▶ Starting session $SESSION_COUNT — next module: $NEXT_MODULE"

    PROMPT="Read SESSION_STATE.md first to confirm the next module to build.
Then read MASTER_AUTODRIVER.md and follow it exactly for that module.

IMPORTANT RULE: If the current SESSION_STATE.md shows STATUS: BLOCKED, do NOT stop.
Instead: scan the BUILD ORDER in MASTER_AUTODRIVER.md for the next module that is NOT blocked and NOT already built.
India pipeline modules are NOT blocked — they are built with a full mock layer (unittest.mock.patch).
The only truly blocked items are those with explicit API credentials that cannot be simulated.
Proceed with the next buildable module.

Do not build any module not in the BUILD ORDER.
Run all pre-build validation steps, build the module, run all tests, run post-build self-review,
update SESSION_STATE.md, README.md, and AAATS_MASTER_BLUEPRINT.md change log, then stop."
  fi

  # Run Claude Code — block until fully complete
  claude \
    --print \
    --output-format text \
    --allowedTools "Read,Write,Edit,Bash" \
    --max-turns 50 \
    "$PROMPT" \
    2>>"$LOG_FILE"

  EXIT_CODE=$?
  log "Claude exited with code: $EXIT_CODE"

  # Wait for filesystem to flush
  sleep 5

  # Read new state
  if [ ! -f "$STATE_FILE" ]; then
    log "ERROR: SESSION_STATE.md missing after session. Claude failed. Check $LOG_FILE"
    exit 1
  fi

  STATE_AFTER=$(tail -1 "$STATE_FILE" 2>/dev/null || echo "")
  log "State before: $STATE_BEFORE"
  log "State after:  $STATE_AFTER"

  # Check if state did not change (Claude stalled)
  if [ "$STATE_BEFORE" = "$STATE_AFTER" ]; then
    log "WARNING: SESSION_STATE.md not updated this session."
    log "Claude may have stalled or hit an error. Check $LOG_FILE"
    log "Stopping to avoid infinite loop."
    exit 1
  fi

  # Check completion
  if echo "$STATE_AFTER" | grep -q "NEXT: ALL_DONE"; then
    log "═══════════════════════════════════════════════"
    log "✅ ALL MODULES BUILT — BUILD COMPLETE"
    log "═══════════════════════════════════════════════"
    exit 0
  fi

  # If STOP_ON_BLOCKED=true and new state is BLOCKED, exit
  if echo "$STATE_AFTER" | grep -q "STATUS: BLOCKED" && [ "$STOP_ON_BLOCKED" = "true" ]; then
    BLOCK_REASON=$(echo "$STATE_AFTER" | grep -oP 'REASON: \K.*' | tr -d '\n')
    log "═══════════════════════════════════════════════"
    log "⚠️  BUILD PAUSED — Dependency needed"
    log "Reason: $BLOCK_REASON"
    log "Re-run once resolved."
    log "═══════════════════════════════════════════════"
    exit 0
  fi

  # Normal continue
  log "Session $SESSION_COUNT complete. Waiting 10s before next session..."
  sleep 10

done

log "⚠️  MAX_SESSIONS ($MAX_SESSIONS) reached. Increase MAX_SESSIONS env var if needed."
log "Current state: $(tail -1 $STATE_FILE)"
exit 1
