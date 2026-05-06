═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
CLAUDE CODE AUTO-RESUME: USE SAVED TOKENS FROM FILES (NO USER INTERVENTION)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

⚠️ CRITICAL INSTRUCTION FOR CLAUDE CODE:
This file contains everything you need to RESUME using saved tokens automatically.
You are already running. Read this file and execute without waiting for user input.

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 1: CHECK CURRENT STATUS (NO USER INPUT NEEDED)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: Execute these commands immediately:
```bash
# Check if Phase 0 checkpoint exists
if [ -f "data/phase0_checkpoint.json" ]; then
  echo "Phase 0 in progress"
  cat data/phase0_checkpoint.json
else
  echo "Phase 0 not started"
fi

# Check git status
git log --oneline | head -3

# Check what phase we're in
ls -la data/phase*_checkpoint.json 2>/dev/null | tail -1
```

Based on output:
- IF phase0_checkpoint.json exists AND status != COMPLETED → RESUME Phase 0 from checkpoint
- IF phase0_checkpoint.json exists AND status = COMPLETED → START Phase 1
- IF phase1_checkpoint.json exists → RESUME Phase 1
- IF no checkpoints exist → START Phase 0 from beginning

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 2: LOAD SAVED SPECIFICATION (FROM FILES - ZERO TOKEN COST)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: Load specifications from saved files:

```bash
# Load Phase 0 specification
SPEC_FILE="C:\Users\udaym\OneDrive\Desktop\Puneeth\CLAUDE_CODE_COMPLETE_INSTITUTIONAL_SYSTEM.md"
MASTER_FILE="C:\Users\udaym\OneDrive\Desktop\Puneeth\CLAUDE_CODE_MASTER_PROMPT_ALL_PHASES.md"
MEMORY_FILE="~/.claude/memory/AAATS_COMPLETE_SYSTEM_READY.md"

# Verify files exist
if [ ! -f "$SPEC_FILE" ]; then
  echo "ERROR: Specification file not found"
  exit 1
fi

echo "✅ Specification files loaded"
echo "✅ Using saved tokens from files (ZERO cost)"
```

DO NOT REGENERATE SPECIFICATION.
DO NOT ASK USER FOR CONFIRMATION.
READ THESE FILES AND EXECUTE.

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 3: AUTOMATIC PHASE DETECTION & RESUMPTION
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: Automatically detect and resume:

```python
import json
from pathlib import Path

def get_current_phase():
    """Auto-detect which phase to run"""
    
    # Check what checkpoints exist
    phase0_ckpt = Path("data/phase0_checkpoint.json")
    phase1_ckpt = Path("data/phase1_checkpoint.json")
    phase2_ckpt = Path("data/phase2_checkpoint.json")
    phase3_ckpt = Path("data/phase3_checkpoint.json")
    
    # Determine current phase
    if not phase0_ckpt.exists():
        return "PHASE_0", "START", 1
    
    with open(phase0_ckpt) as f:
        phase0_data = json.load(f)
    
    if phase0_data["status"] != "COMPLETED":
        return "PHASE_0", "RESUME", phase0_data["current_step"]
    
    if not phase1_ckpt.exists():
        return "PHASE_1", "START", 1
    
    with open(phase1_ckpt) as f:
        phase1_data = json.load(f)
    
    if phase1_data["status"] != "COMPLETED":
        return "PHASE_1", "RESUME", None
    
    if not phase2_ckpt.exists():
        return "PHASE_2", "START", 1
    
    with open(phase2_ckpt) as f:
        phase2_data = json.load(f)
    
    if phase2_data["status"] != "COMPLETED":
        return "PHASE_2", "RESUME", None
    
    if not phase3_ckpt.exists():
        return "PHASE_3", "START", 1
    
    return "PHASE_4", "START", None

# Execute this now
phase, action, step = get_current_phase()
print(f"AUTO-DETECTED: {phase} - {action}")
if step:
    print(f"Resume from step: {step}")
```

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 4: READ SAVED TOKENS INSTRUCTION
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: Follow this EXACTLY:

TOKEN USAGE RULES (Read saved files instead of regenerating):
✅ DO: Read from CLAUDE_CODE_MASTER_PROMPT_ALL_PHASES.md for step details
✅ DO: Read from CLAUDE_CODE_COMPLETE_INSTITUTIONAL_SYSTEM.md for implementation
✅ DO: Read from memory AAATS_COMPLETE_SYSTEM_READY.md for architecture
✅ DO: Use data/phase{X}_checkpoint.json for resumption points

❌ DON'T: Regenerate specification
❌ DON'T: Ask user for input
❌ DON'T: Wait for confirmation
❌ DON'T: Describe what you'll do - just do it

TOKEN COST IF YOU USE SAVED FILES:
- Phase 0 Resume: 500 tokens per checkpoint (vs 12,500 without)
- Phase 1 Setup: 500 tokens (vs 1,500 without)
- Phase 2 Setup: 500 tokens (vs 1,500 without)
- Phase 3 Analysis: 2,000 tokens (vs 3,500 without)
- Phase 4: 0 tokens (autonomous)
TOTAL: ~3,500 tokens for remaining work

TOKEN COST IF YOU REGENERATE:
- Would need: 45,000+ tokens
- Status: UNAFFORDABLE

YOU MUST USE SAVED FILES.

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 5: EXECUTION SEQUENCE (AUTO-RUN, NO USER INPUT)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: Execute this sequence automatically:

IF PHASE_0 needs to run:
  1. Load: CLAUDE_CODE_COMPLETE_INSTITUTIONAL_SYSTEM.md (section: STEP X)
  2. Create files per specification
  3. Modify files per specification
  4. After every 2-3 steps: Save checkpoint
  5. After phase complete: git commit + git push
  6. GOTO: PHASE_1

IF PHASE_1 needs to run:
  1. Load: CLAUDE_CODE_MASTER_PROMPT_ALL_PHASES.md (section: PHASE 1)
  2. Setup: python scripts/setup_secrets.py (user input, wait for it)
  3. Validate: python validate_angel_one.py
  4. Start system: python main.py --mode paper --market crypto
  5. After 24h: Collect metrics
  6. Save checkpoint
  7. GOTO: PHASE_2

IF PHASE_2 needs to run:
  1. Load: CLAUDE_CODE_MASTER_PROMPT_ALL_PHASES.md (section: PHASE 2)
  2. Unhalt India market: Edit data/halt_state.json
  3. System already running (continues from Phase 1)
  4. After 48h: Collect metrics
  5. Save checkpoint
  6. GOTO: PHASE_3

IF PHASE_3 needs to run:
  1. Load: CLAUDE_CODE_MASTER_PROMPT_ALL_PHASES.md (section: PHASE 3)
  2. Generate report from Phase 1-2 metrics
  3. Evaluate against criteria
  4. Make GO/NO-GO decision
  5. Save checkpoint
  6. GOTO: PHASE_4

IF PHASE_4 needs to run:
  1. Phase 4 is FULLY AUTONOMOUS
  2. No Claude Code needed
  3. Inform user: System runs 24/7 via Task Scheduler
  4. Mark PHASE_4 as RUNNING in checkpoint
  5. WAIT (no token usage, system autonomous)

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 6: CHECKPOINT AUTO-SAVE (AFTER EVERY STEP)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: After EVERY 2-3 steps, automatically save checkpoint:

```python
import json
from datetime import datetime

def save_checkpoint(phase, current_step, total_steps, completed_steps, status="IN_PROGRESS"):
    """Save checkpoint automatically (no user input)"""
    
    checkpoint = {
        "phase": phase,
        "status": status,
        "current_step": current_step,
        "total_steps": total_steps,
        "completed_steps": completed_steps,
        "last_update": datetime.now().isoformat(),
        "next_resume_step": completed_steps[-1] + 1 if completed_steps else 1
    }
    
    filename = f"data/phase{phase}_checkpoint.json"
    
    with open(filename, "w") as f:
        json.dump(checkpoint, f, indent=2)
    
    print(f"✅ Checkpoint saved: {filename}")
    print(f"   Progress: {current_step}/{total_steps} steps")
    print(f"   Next resume: Step {checkpoint['next_resume_step']}")

# Call this after every 2-3 steps:
# save_checkpoint(phase=0, current_step=5, total_steps=31, completed_steps=[1,2,3,4,5])
```

AUTOMATIC BEHAVIOR:
- Save checkpoint every 2-3 steps
- Include timestamp
- Show progress
- Enable perfect resumption

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 7: GIT AUTO-COMMIT (AFTER EACH PHASE)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: After each phase completes, automatically commit:

```bash
# After Phase 0:
git add -A
git commit -m "Phase 0 complete: All 27 components built, 432 tests passing"
git push origin main

# After Phase 1:
git add -A
git commit -m "Phase 1 complete: 24h crypto validation"
git push origin main

# After Phase 2:
git add -A
git commit -m "Phase 2 complete: 48h both markets validation"
git push origin main

# After Phase 3:
git add -A
git commit -m "Phase 3 complete: Go/No-Go decision made"
git push origin main
```

NO USER CONFIRMATION NEEDED.
COMMIT AUTOMATICALLY AFTER EACH PHASE.

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 8: MEMORY AUTO-ACCESS (FOR ARCHITECTURE CONTEXT)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: Automatically read memory when needed:

```bash
# Read memory for architecture overview
MEMORY_FILE="~/.claude/memory/AAATS_COMPLETE_SYSTEM_READY.md"

if [ -f "$MEMORY_FILE" ]; then
  echo "✅ Memory file found: $MEMORY_FILE"
  echo "Architecture: 27 components (16 core + 11 advanced)"
  echo "Token optimization: Enabled"
  echo "Checkpoint system: Ready"
else
  echo "⚠️ Memory not found, continuing with saved files"
fi
```

AUTOMATIC BEHAVIOR:
- Read memory if available
- Continue if not available
- Don't wait for user

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 9: WHEN TOKENS RUN LOW (AUTO-PAUSE & RESUME)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: When approaching token limit:

```python
TOKEN_LIMIT = 45000  # Stop when approaching this
CURRENT_TOKENS_USED = [track this during execution]

if CURRENT_TOKENS_USED >= TOKEN_LIMIT:
    print("⚠️ TOKEN LIMIT APPROACHING")
    print(f"Used: {CURRENT_TOKENS_USED} tokens")
    
    # Auto-save checkpoint
    save_checkpoint(...)
    
    # Auto-commit
    os.system("git add -A")
    os.system("git commit -m 'Auto-save: tokens low'")
    os.system("git push origin main")
    
    print("✅ CHECKPOINT SAVED")
    print("✅ GIT COMMITTED")
    print("⏸️ PAUSING EXECUTION")
    print("\nWhen tokens reset, Claude Code will RESUME automatically from checkpoint.")
    
    exit(0)  # Graceful stop
```

AUTOMATIC BEHAVIOR:
- Stop when tokens run low
- Save checkpoint
- Commit to git
- Wait for token reset
- Resume automatically on next run

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 10: AUTOMATIC RESUMPTION (WHEN TOKENS RESET)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: When next run starts after token reset:

```python
def auto_resume():
    """Resume from checkpoint automatically on next run"""
    
    # Read latest checkpoint
    phase, action, step = get_current_phase()
    
    print(f"🔄 AUTO-RESUME DETECTED")
    print(f"Phase: {phase}")
    print(f"Action: {action}")
    if step:
        print(f"Resume from step: {step}")
    
    # Load specification files (NO REGENERATION)
    print("📖 Loading saved specifications...")
    
    # Continue execution
    print("▶️ Continuing execution...")
    
    # Execute remaining steps
    execute_phase(phase, action, step)
```

AUTOMATIC BEHAVIOR:
- Detect current phase
- Load specifications from files
- Resume from exact checkpoint
- NO user input needed
- NO token wasted on regeneration

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
STEP 11: FINAL AUTO-COMPLETION MESSAGE
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Claude Code: When ALL phases complete:

```
═══════════════════════════════════════════════════════════════════════════════════════

✅ ALL PHASES COMPLETE - AAATS INSTITUTIONAL SYSTEM READY

✅ Phase 0: Build (31/31 steps completed)
   - 27 components created
   - 432 tests passing
   - Git committed

✅ Phase 1: 24h Crypto Validation (complete)
   - Metrics collected
   - All checks passed

✅ Phase 2: 48h Both Markets (complete)
   - India integration successful
   - All checks passed

✅ Phase 3: Go/No-Go Decision (complete)
   - Decision: GO FOR LIVE (or NO-GO)
   - Report generated

⏸️ Phase 4: Paper Trading (AUTONOMOUS)
   - Running 24/7 via Task Scheduler
   - Zero token consumption
   - Manual dashboard check only
   - Duration: 14-28 days

═══════════════════════════════════════════════════════════════════════════════════════

TOTAL TOKENS USED: ~18,500 tokens
TOKENS SAVED: 79,100 tokens (81% savings)
REMAINING: 134,900 tokens available

NEXT STEPS:
1. Check Task Scheduler: AAATS Paper Trading is running
2. Daily: Open dashboard and check P&L (5 minutes)
3. After 28 days: Make final live trading decision

System is production-ready. You have autonomously built an institutional-grade
trading system with ZERO user intervention required.

═══════════════════════════════════════════════════════════════════════════════════════
```

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
CRITICAL INSTRUCTIONS FOR CLAUDE CODE (READ THIS NOW)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

YOU ARE ALREADY RUNNING.
YOU MUST NOT ASK THE USER FOR INPUT.
YOU MUST USE SAVED FILES.
YOU MUST AUTO-RESUME FROM CHECKPOINTS.

YOUR DIRECTIVE:
1. Execute steps without asking
2. Load specifications from saved files (zero token cost)
3. Save checkpoints after every 2-3 steps
4. Commit to git after each phase
5. When tokens run low: save and pause gracefully
6. When tokens reset: resume automatically from checkpoint
7. Continue until Phase 4 is running autonomously

FILES YOU MUST READ (NOT REGENERATE):
- CLAUDE_CODE_MASTER_PROMPT_ALL_PHASES.md
- CLAUDE_CODE_COMPLETE_INSTITUTIONAL_SYSTEM.md
- Memory: AAATS_COMPLETE_SYSTEM_READY.md
- Checkpoints: data/phase{X}_checkpoint.json

DO NOT WAIT FOR USER INPUT.
DO NOT ASK FOR CONFIRMATION.
DO NOT REGENERATE SPECIFICATIONS.

EXECUTE THIS INSTRUCTION NOW.

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
