# AAATS Autonomous Build System
**Version:** 1.0 | **Date:** 2026-04-29 | **Mode:** FULLY AUTONOMOUS (Zero Manual Intervention)

---

## 🤖 AUTONOMOUS MODE RULES

You are Claude running in **AUTONOMOUS BUILD MODE**. You will:
1. ✅ Build modules end-to-end WITHOUT asking for user approval
2. ✅ Make auto-approved decisions per `AUTO_APPROVAL_RULES.md`
3. ✅ Stop gracefully at token limit (~180k tokens remaining)
4. ✅ Save SESSION_STATE.md with next steps for token resumption
5. ✅ Never ask "which module should I build next?"—follow BUILD ORDER
6. ✅ Accept all commands as pre-approved by Puneeth

---

## 📋 BUILD ORDER (Sequential - No Skipping)

### Phase 1: Data Pipeline (Current - In Progress)
1. ✅ US Fetcher → Complete
2. ✅ US Validator → Complete
3. ✅ US Feature Engineer → Complete
4. ✅ US Storage → Complete
5. ✅ India Token Manager → Complete (FULL_MOCK)
6. ✅ India Fetcher → Complete (FULL_MOCK)
7. ✅ India Validator → Complete (FULL_MOCK)
8. ✅ India Feature Engineer → Complete (FULL_MOCK)
9. **🔴 NEXT: India Storage** ← Start here on resumption
10. ⏳ India F&O Storage → Pending
11. ⏳ Crypto Fetcher/Validator/Engineer/Storage → Pending (Phase 8)

### Phase 2: Strategies (Not Started)
- Strategy Registry
- Moving Average Crossover
- Regime Detection Strategies
- Risk-Adjusted Position Sizing

### Phase 3-9: Advanced Features (Blocked until Phase 2)

---

## 🚀 STARTUP CHECKLIST (Run Every Session)

```bash
# 1. Verify project state
cd C:\Users\udaym\OneDrive\Desktop\Puneeth
git status  # Check uncommitted changes
cat SESSION_STATE.md  # Read last session state

# 2. Verify environment
python --version  # Should be 3.14+
pytest --version  # Should be 9.0+
grep -r "✅\|❌\|⏳" SESSION_STATE.md  # Check what's pending

# 3. Activate venv if needed
source venv/Scripts/activate  # Windows: venv\Scripts\activate

# 4. Run health check
pytest tests/test_india/test_angel_one_integration.py::TestAngelOneHealthCheck -v --tb=short
```

**STOP immediately if:**
- ❌ Tests fail
- ❌ Git status shows uncommitted critical files
- ❌ Angel One credentials missing from .env

---

## 🔧 MODULE BUILD PROCESS (Template)

For each module, follow this EXACT sequence:

### Step 1: PRE-BUILD VALIDATION (5 min)
```bash
# Check module spec exists
ls -la {module_path}/SPEC.md 2>/dev/null || echo "⚠️ No SPEC for this module"

# Check dependencies exist
grep -r "from {dependency}" tests/ 2>/dev/null | head -5

# Verify .env has required credentials (if market-specific)
grep "^{MARKET}__" .env | wc -l
```

### Step 2: DESIGN REVIEW (5 min)
Read the spec. Answer:
- What is the module's responsibility?
- What inputs does it consume?
- What outputs does it produce?
- What error cases must it handle?

### Step 3: CODE GENERATION (15-30 min)
- Write module file with docstrings
- Implement all error handling
- Use dependency injection (no hardcoded paths)
- Add logging for debugging

### Step 4: UNIT TESTS (10-20 min)
- Mock all external dependencies
- Test happy path
- Test error cases (invalid input, missing deps, etc.)
- Run: `pytest tests/test_{market}/{module_test}.py -v`

### Step 5: INTEGRATION TEST (10-15 min)
- For API modules: test with real credentials from .env
- For storage modules: test database operations
- Run: `pytest tests/test_{market}/{module_integration}.py -v -s`

### Step 6: COMPLETION REPORT
Write to SESSION_STATE.md:
```
## Module: {name}
- **Status:** ✅ COMPLETE
- **Files Created:** {list}
- **Tests:** {passed} passed, {skipped} skipped
- **Token Usage:** ~{estimate}k
- **Next:** {next_module}
```

### Step 7: GIT COMMIT (Atomic)
```bash
git add {files}
git commit -m "Phase {N}: {module_name} — tests passing, ready for {next_phase}"
```

---

## ⚠️ AUTO-APPROVAL RULES

### ✅ CLAUDE CAN AUTO-APPROVE:
1. **Code changes** to incomplete modules (Phase 1.9 India Storage, Phase 2+)
2. **Test creation/modification** for modules being built
3. **Documentation updates** to SPEC.md, README.md sections
4. **Dependency additions** to requirements.txt (if in venv)
5. **File reorganization** (moving, renaming files)
6. **Git commits** for completed modules

### ❌ REQUIRES USER APPROVAL (but Claude proceeds with checkpoint):
1. **Changes to .env** (credentials) — LOG but do NOT modify
2. **Deletions of working code** — WARN and checkpoint
3. **Breaking changes** to Phase 0 (foundation)
4. **Changes to MASTER_AUTODRIVER.md, AAATS_MASTER_BLUEPRINT.md** — WARN only
5. **Changes to deploy/live trading config** — NEVER, flag and stop

**Checkpoint format when blocked:**
```
⚠️ APPROVAL NEEDED: {what} in {file}
   Reason: {why_approval_needed}
   Suggested action: {what_Claude_recommends}
   STATUS: ⏸️ PAUSED — waiting for user to review SESSION_STATE.md
   
Next token session: Resume from this checkpoint with:
   claude code "Continue from last checkpoint: [read SESSION_STATE.md]"
```

---

## 💾 TOKEN MANAGEMENT

### Token Budget Per Session
- **Hard limit:** 180,000 tokens (stop building, save state)
- **Soft limit:** 160,000 tokens (wrap up current module)
- **Reserve:** 20,000 tokens (final checkpoint write)

### Token Tracking (Estimate)
- Module design: ~2k tokens
- Code generation: ~5-15k tokens per module
- Test writing: ~3-8k tokens per module
- Integration testing: ~2-5k tokens
- Completion report: ~1k tokens
- **Per module average: ~15-30k tokens**

### When Token Limit Reached
1. **Immediately STOP building**
2. **Finish current operation** (don't abandon mid-file)
3. **Write SESSION_STATE.md** with:
   - ✅ Modules completed this session
   - 🔴 What was being built (incomplete)
   - ⏳ Exact next step to resume from
   - 📊 Token usage estimate
4. **Commit working code** (git add, git commit)
5. **Log status:**
   ```
   === TOKEN LIMIT REACHED ===
   Session tokens used: ~{estimate}k
   Next session: Run exactly this command:
   
   claude code "
   cd C:\Users\udaym\OneDrive\Desktop\Puneeth
   cat SESSION_STATE.md
   [CONTINUE_FROM_CHECKPOINT]
   "
   ```

---

## 🔄 RESUMPTION PROTOCOL (When Token Restored)

When starting new session with tokens restored:

```bash
# 1. Read state
cat SESSION_STATE.md

# 2. Identify checkpoint
grep "NEXT_STEP\|⏳\|PAUSED" SESSION_STATE.md

# 3. Resume exactly where stopped
# (All context is in SESSION_STATE.md)

# 4. Continue building the next module
```

**Do NOT re-read full project context.** Just read SESSION_STATE.md. All context needed is there.

---

## 🎯 SESSION PROTOCOL

### START SESSION
```bash
echo "=== AUTONOMOUS BUILD SESSION START ==="
echo "Reading state..."
cat SESSION_STATE.md | head -20
echo ""
echo "Verified: Ready to build"
```

### END SESSION (Token limit OR completion)
```bash
echo "=== AUTONOMOUS BUILD SESSION END ==="
echo "Writing final state to SESSION_STATE.md..."
# Append checkpoint to SESSION_STATE.md
echo "" >> SESSION_STATE.md
echo "## Session $(date): Status checkpoint" >> SESSION_STATE.md
```

### COMMIT PROTOCOL
- Commit after EVERY completed module
- Message format: `Phase {N}: {module_name} — {brief_status}`
- Example: `Phase 1: India Storage — tests passing, real API integration verified`

---

## 🛠️ EMERGENCY PROTOCOLS

### If Tests Fail
1. Read error message carefully
2. Identify root cause
3. Fix code
4. Re-run tests
5. If > 3 failures: write checkpoint and PAUSE
   ```
   ⚠️ UNABLE TO FIX: {module}
   Error: {description}
   Attempted fixes: {list}
   STATUS: ⏸️ PAUSED — Puneeth should review next session
   ```

### If Angel One API Fails
1. Verify .env credentials are correct
2. Run: `pytest tests/test_india/test_angel_one_integration.py::TestAngelOneHealthCheck -v`
3. If still fails: checkpoint and pause
   ```
   ⚠️ ANGEL ONE API ISSUE
   Error: {specific_error}
   Next: Puneeth verify credentials in .env and test manually
   ```

### If Git Commit Fails
1. Run `git status`
2. Resolve conflicts manually
3. Re-attempt commit
4. If still fails: checkpoint with git state

---

## 📊 SESSION_STATE.md FORMAT

Maintain this file at root of project. Update after EACH module:

```markdown
# AAATS Build State

## Current Session
- **Start time:** {timestamp}
- **Phase:** {phase_number}
- **Module:** {current_module_name}
- **Status:** {BUILDING|COMPLETE|PAUSED|FAILED}

## Completed This Session
- ✅ Module 1: {status}
- ✅ Module 2: {status}

## Current Module
- 🔴 India Storage
  - Step 1: PRE-BUILD VALIDATION → ✅ DONE
  - Step 2: DESIGN REVIEW → ✅ DONE
  - Step 3: CODE GENERATION → 🔴 IN PROGRESS
    - File: markets/india/storage.py
    - Next: Write FeatureStore class
  - Step 4: UNIT TESTS → ⏳ PENDING
  - Step 5: INTEGRATION TEST → ⏳ PENDING

## Next Steps
1. Complete India Storage (current)
2. Build India F&O Storage
3. Run Phase 1 integration tests
4. Begin Phase 2 (Strategies)

## Token Usage
- Session start: 200,000 available
- Used so far: ~25,000
- Remaining: ~175,000

## Notes
- Angel One API: ✅ Verified working
- Dependencies: All installed
- No blockers
```

---

## ✅ SUCCESS CRITERIA

Project is **COMPLETE** when:
- ✅ All Phase 0-7 modules built and tested
- ✅ Phase 8 (Crypto) enabled but not live
- ✅ Paper trading runs for 3+ months without manual intervention
- ✅ All tests passing
- ✅ Risk engine active (kill switches working)
- ✅ Live trading ready (Phase 9 skeleton)

---

## 🚨 ABORT CONDITIONS

**STOP and PAUSE if:**
1. ❌ Tests fail 3+ times on same module
2. ❌ Angel One API unreachable (market offline)
3. ❌ Credentials missing from .env
4. ❌ Merge conflicts in git
5. ❌ Approval checkpoint hit (wait for user)
6. ❌ Token limit reached

For each abort: Write detailed checkpoint to SESSION_STATE.md.

---

## 📝 COMMAND FOR CLAUDE CODE

Copy and paste this entire AUTO_BUILD_SYSTEM.md as context when starting Claude Code autonomous sessions. Then run:

```
claude code "
AUTONOMOUS MODE: ENABLED
TOKEN BUDGET: 180,000 tokens
BUILD ORDER: See AUTO_BUILD_SYSTEM.md

Instructions:
1. Read SESSION_STATE.md first
2. Follow BUILD ORDER — no skipping
3. Use AUTO_APPROVAL_RULES.md for decisions
4. Stop at token limit (180k remaining)
5. Commit after each module
6. Update SESSION_STATE.md after each session

START_BUILD_SESSION
"
```

---

**Created:** 2026-04-29 | **For:** Puneeth | **Mode:** Autonomous (Zero Manual Intervention)
