# Auto-Approval Rules for Claude Autonomous Mode

**Decision Matrix:** What Claude can auto-approve vs. what requires checkpoint

---

## ✅ CLAUDE CAN AUTO-APPROVE (Proceed Without User Input)

### 1. Code Implementation
- ✅ Write new .py files for incomplete modules
- ✅ Modify incomplete module files (Phase 1.9 onwards, Phase 2+)
- ✅ Add helper functions, utilities
- ✅ Refactor code in incomplete modules
- **RULE:** If module is marked ⏳ (pending) or 🔴 (in progress), changes are auto-approved

### 2. Test Files
- ✅ Create unit tests for modules being built
- ✅ Create integration tests
- ✅ Modify test fixtures, mocks
- ✅ Add test utilities
- **RULE:** Tests are always auto-approved if they make the build pass

### 3. Documentation
- ✅ Write/update SPEC.md files for modules
- ✅ Update module docstrings
- ✅ Write inline code comments
- ✅ Update file-level documentation
- **RULE:** Pure documentation is always auto-approved

### 4. Configuration
- ✅ Add new Python dependencies to requirements.txt (and pip install)
- ✅ Add new environment variables to .env.example (NOT .env itself)
- ✅ Create/update config schema definitions
- **RULE:** Config additions that enable new functionality auto-approved

### 5. File Organization
- ✅ Create new directories (markets/, tests/, config/)
- ✅ Rename/move files within project
- ✅ Create new test directories
- **RULE:** Organizational changes auto-approved

### 6. Git Operations
- ✅ `git add` and `git commit` after module completion
- ✅ `git status` checks
- ✅ Create feature branches
- **RULE:** Commits for completed modules auto-approved

### 7. Dependency Installation
- ✅ `pip install` new packages (if in requirements.txt)
- ✅ Run `pytest` to verify tests
- ✅ Run tests with real Angel One credentials from .env
- **RULE:** Installations that make tests pass auto-approved

---

## ⚠️ CHECKPOINT REQUIRED (Pause and Log, Then Proceed)

### 1. Modifications to Core Files
**Files:** MASTER_AUTODRIVER.md, AAATS_MASTER_BLUEPRINT.md, README.md
- 🟡 Log the change to SESSION_STATE.md
- 🟡 Write reason for change
- 🟡 Note: Change still proceeds (not user-blocking)
- **Example:**
  ```
  ⚠️ DOCUMENTATION UPDATE: AAATS_MASTER_BLUEPRINT.md
  Section: Prompting Guidelines
  Change: Updated to reflect new Phase 1 structure
  Reason: Phase 1.9 (India Storage) now documented
  STATUS: ✅ PROCEEDING (logged for audit)
  ```

### 2. Error Handling Decisions
**When tests fail:**
- 🟡 Attempt fix up to 3 times
- 🟡 Log each attempt to SESSION_STATE.md
- 🟡 If 3+ failures: PAUSE and checkpoint
  ```
  ⚠️ TEST FAILURE CHECKPOINT: {module_name}
  Error: {detailed_error}
  Attempts: 3
  STATUS: ⏸️ PAUSED — Puneeth should review
  ```

### 3. API Integration Issues
**When Angel One API fails:**
- 🟡 Verify .env credentials exist
- 🟡 Run health check test
- 🟡 If still fails: PAUSE and checkpoint
  ```
  ⚠️ API INTEGRATION CHECKPOINT: Angel One
  Error: {specific_error}
  Root cause: {analysis}
  STATUS: ⏸️ PAUSED — verify credentials and test manually
  ```

### 4. Breaking Changes to Phase 0
**Cannot change completed modules (Phase 0: Foundation)**
- 🟡 If necessary: Log reason and stop
- 🟡 Write checkpoint
- 🟡 Require user approval (cannot proceed)
  ```
  ❌ BLOCKED: Phase 0 (Foundation) modification required
  Module: {module_name}
  Reason: {why_change_needed}
  STATUS: ⏹️ STOPPED — User approval required
  ```

---

## ❌ USER APPROVAL REQUIRED (Cannot Proceed Automatically)

### 1. Credentials/Security Changes
- ❌ Modifying .env file directly (API keys, credentials)
- ❌ Exposing secrets in logs or test output
- ❌ Creating new credential variables
- **Action:** Checkpoint and STOP
  ```
  ❌ SECURITY CHECKPOINT: .env modification
  Proposed change: {what}
  Reason: {why}
  STATUS: ⏹️ STOPPED — User approval required
  Next: Puneeth manually update .env and resume
  ```

### 2. Deletions of Working Code
- ❌ Deleting completed module files
- ❌ Removing Phase 0 code
- ❌ Removing test files that pass
- **Action:** Checkpoint and STOP
  ```
  ❌ DELETION CHECKPOINT
  File: {file_path}
  Current status: {working|passing tests}
  Reason for deletion: {what_claude_thinks}
  STATUS: ⏹️ STOPPED — User approval required
  ```

### 3. Live Trading Configuration
- ❌ Modifying SYSTEM__TRADING_MODE=paper
- ❌ Changing risk caps (MAX_RISK_PER_TRADE, DRAWDOWN_HALT)
- ❌ Enabling live trading features
- **Action:** HARD STOP, cannot proceed
  ```
  ❌ CRITICAL SECURITY STOP: Live trading config
  Attempted change: {what}
  STATUS: ⏹️ HARD STOPPED — This is irreversible. User must manually verify.
  ```

### 4. Database/Data Modifications
- ❌ Deleting data from sqlite databases
- ❌ Clearing audit trails
- ❌ Modifying historical data
- **Action:** Checkpoint and STOP
  ```
  ❌ DATA MODIFICATION CHECKPOINT
  Database: {which_db}
  Operation: {what}
  Rows affected: {count}
  STATUS: ⏹️ STOPPED — User approval required
  ```

---

## 🎯 Decision Tree

```
Claude is about to make a change. Ask:

1. Is the file in Phase 0 (Foundation)?
   → YES: Requires checkpoint (log but can proceed)
   → NO: Continue to 2

2. Is it a credential/security change?
   → YES: ❌ HARD STOP, cannot proceed
   → NO: Continue to 3

3. Is it a deletion of working code?
   → YES: ⚠️ Checkpoint and pause
   → NO: Continue to 4

4. Is it a test file or new module code?
   → YES: ✅ AUTO-APPROVE
   → NO: Continue to 5

5. Is it documentation or config schema?
   → YES: ✅ AUTO-APPROVE
   → NO: Continue to 6

6. Is it a git commit?
   → YES: ✅ AUTO-APPROVE
   → NO: Continue to 7

7. Is it an error fix attempt (< 3 failures)?
   → YES: ✅ AUTO-APPROVE
   → NO: ⚠️ Checkpoint and pause (3+ failures)

Result:
- ✅ AUTO-APPROVE: Proceed immediately
- ⚠️ CHECKPOINT: Log and proceed
- ❌ STOP: Wait for user review of SESSION_STATE.md
```

---

## 📋 Checkpoint Template

When any approval-required change is detected:

```markdown
## Session Checkpoint: {timestamp}

### Decision Point
- **Type:** {approval_required|checkpoint|hard_stop}
- **File:** {path}
- **Change:** {what_was_going_to_happen}

### Reason
{why_this_approval_is_needed}

### Claude's Recommendation
{what_Claude_suggests_user_do}

### Status
- ⚠️ PAUSED (if checkpoint)
- ⏸️ STOPPED (if user approval needed)
- ⏹️ HARD STOPPED (if critical security issue)

### Next Step
1. Puneeth reviews this checkpoint
2. If approved: Update .env or provide approval
3. Resume with: `claude code "[read SESSION_STATE.md and continue]"`
```

---

## ✅ Token-Efficient Decision Making

To avoid wasting tokens asking for approval:

1. **Pre-check before coding:** Read this file
2. **Categorize change:** Use decision tree above
3. **If ✅ AUTO-APPROVE:** Proceed immediately
4. **If ⚠️ CHECKPOINT:** Log and continue
5. **If ❌ STOP:** Write checkpoint, do NOT code

**Never ask "should I...?"** Just check this file and decide.

---

## 🔄 Escalation Path

**If Claude is unsure about a decision:**

```
1. Default to ⚠️ CHECKPOINT (safe option)
2. Log the ambiguity: "Unsure if X is auto-approved"
3. Write checkpoint with two options:
   - Option A: Proceed with X
   - Option B: Skip X, move to next module
4. Pause and wait for next token session
```

---

**Created:** 2026-04-29 | **Updated:** AUTO_BUILD_SYSTEM.md v1.0
