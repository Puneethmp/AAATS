# AAATS Autonomous Build Framework

**Purpose:** Enable Claude to build the entire AAATS project end-to-end without manual intervention, resuming automatically when token limits are reached.

**Last Updated:** 2026-04-29

---

## BUILD SEQUENCE (Do NOT Skip Phases)

### Phase 0: Foundation ✅ COMPLETE
- Skip entirely. Do not revisit.

### Phase 1: Data Pipeline (IN PROGRESS)
1. ✅ US Fetcher → Validator → Feature Engineer → Storage
2. ✅ India Token Manager → Fetcher → Validator → Feature Engineer
3. ✅ India F&O Fetcher → Validator → Feature Engineer
4. ⏳ **India Storage** (NEXT)
5. → Crypto Fetcher (Phase 8, defer)

### Phase 2: Strategies (NOT STARTED)
Build momentum, mean-reversion, volatility, ML strategies. Each strategy: signal logic → backtest → validation.

### Phase 3: Regime Detection (NOT STARTED)
Market regime classification. Build on Phase 2 data.

### Phase 4: ML Models (NOT STARTED)
Feature engineering, model training, hyperparameter tuning, walk-forward validation.

### Phase 5: Risk Management (NOT STARTED)
Position sizing engine, drawdown guards, kill switches, portfolio risk aggregation.

### Phase 6: Paper Trading (NOT STARTED)
End-to-end system integration, real-time execution simulation, performance tracking.

### Phase 7: Learning System (NOT STARTED)
Backtest-to-live gap analysis, trade journal, continuous learning loops.

### Phase 8: Crypto (NOT STARTED)
Extend to crypto markets.

### Phase 9: Live Trading (NOT STARTED)
Final validation, live deployment with risk gates.

---

## AUTONOMOUS EXECUTION RULES

### Token Management
1. **Stop Point:** When you estimate you have <10k tokens remaining, STOP immediately
2. **Before Stopping:**
   - Update SESSION_STATE.md with exact current status
   - Commit any completed code to files
   - Leave clear instructions for next session
3. **Resume:** Read SESSION_STATE.md first, continue from last checkpoint

### What Claude Can Decide (No User Approval Needed)
✅ **Auto-Approve These:**
- Code implementation following spec
- Test writing and execution
- Bug fixes within module scope
- Documentation/docstrings
- Refactoring within same module
- Library/dependency additions (if not security-critical)
- File organization/structure
- Error handling improvements

❌ **MUST Ask User (Stop & Wait):**
- Risk rule changes (position sizing, drawdown %, kill switches)
- Architecture changes (add new market, new phase structure)
- Database schema changes
- API integration changes (new broker/data provider)
- Credentials or secret handling
- Backtest integrity changes (lookahead bias, cost model)
- Performance requirement changes

### Code Quality Standards (Auto-Check, Never Skip)
1. **Pre-Commit Validation:**
   - All imports must resolve (test with `python -c "import X"`)
   - All tests must pass before moving to next module
   - No hardcoded credentials or secrets
   - Type hints required for all functions
   - Docstrings required (Google style)

2. **Build Checkpoint:**
   - After each module: run its test suite
   - Only proceed to next module if tests pass
   - If tests fail: fix before proceeding
   - Never skip failed tests

3. **Integration Checkpoint (Every Phase):**
   - After all modules in phase complete: run `pytest tests/test_<phase>/` 
   - Before proceeding to next phase: verify phase is production-ready

### File Management
- **NEVER delete** completed, tested modules
- **NEVER modify** .env file (user manages credentials)
- **NEVER modify** MASTER_AUTODRIVER.md, AAATS_MASTER_BLUEPRINT.md, README.md, ANGEL_ONE_SETUP.md without explicit permission
- **OK to create** new test files, new module files, new config
- **OK to update** SESSION_STATE.md frequently (this is your scratchpad)

### Session Structure
Each session:
1. Read SESSION_STATE.md first (5 seconds)
2. Verify all dependencies from last session still work
3. Continue from exact checkpoint in SESSION_STATE.md
4. Build one complete module at a time
5. Test thoroughly before marking complete
6. Update SESSION_STATE.md after each module
7. When approaching token limit: stop, update SESSION_STATE.md, exit

---

## DECISION FRAMEWORK: When Claude Approves (Without Asking User)

**Risk Rule Questions:**
- "Should position size be 1.5% or 2%?" → Use AAATS_MASTER_BLUEPRINT.md spec (1.5% equity, 1.0% F&O) — NOT your decision
- "Should drawdown halt be -15% or -20%?" → Use spec — NOT your decision
- "What should max portfolio exposure be?" → Use spec — NOT your decision

**Design Questions:**
- "Should I use Redis or SQLite for cache?" → If spec says SQLite, use SQLite. If spec is silent, you can decide (but document it)
- "What columns should the trade journal have?" → Design it logically; add what's useful for learning
- "How many features for the ML model?" → Design based on Phase 4 spec; if silent, you design (document assumptions)

**Test Coverage:**
- "Should I write this test?" → YES, always. If it tests a module requirement, write it.
- "Are 3 test cases enough?" → If spec requires coverage, write enough to prove it. Aim for >80% coverage per module.

**Performance:**
- "Should data loading take <100ms or <1s?" → If spec is silent, reasonable defaults apply (100ms is better, 1s is acceptable)
- "How many backtest iterations?" → Follow spec. If spec is silent, use walk-forward with 20%+ test set minimum.

---

## STOPPING CRITERIA (Required, Non-Negotiable)

Stop and exit immediately if:
1. Token limit approaching (< 10k remaining)
2. You encounter an error you cannot resolve in 3 attempts
3. You need user input on a risk rule or architecture decision
4. A test fails and fixing requires changing spec/design

In all cases:
- Update SESSION_STATE.md completely
- Describe the blocker clearly
- List exact next steps for resume

---

## How to Resume After Token Reset

1. **On restart:** Read entire SESSION_STATE.md (it tells you exactly where you were)
2. **Verify dependencies:** Run health checks from SESSION_STATE.md
3. **Continue:** Execute "Next Step" listed in SESSION_STATE.md
4. **If unclear:** Ask user for 1-line clarification (minimize token cost)

---

## TOKEN EFFICIENCY (Critical)

**Minimize Output:**
- Do NOT explain every line of code
- Do NOT recap what you just did
- Do NOT output full file contents unless asked
- Do output only: test results, errors, completion confirmation, file changes summary

**Minimize Thinking:**
- Use SESSION_STATE.md as reference (don't re-derive context)
- Refer to MASTER_AUTODRIVER.md sections by name, don't reread
- If you've already written tests for a pattern, reuse the pattern

**Example Efficient Session:**

```
Session Start:
- Read SESSION_STATE.md (45 tokens)
- Verify dependencies (120 tokens)
- Build India Storage module (1200 tokens)
- Test India Storage (300 tokens)
- Update SESSION_STATE.md (150 tokens)
= 1815 tokens used

Session Stop (approaching limit):
[Exit, wait for token reset, resume next session]
```

**Example Inefficient Session:**

```
Session Start:
- Recap entire project architecture (800 tokens) ❌ You have MASTER_AUTODRIVER.md
- Reread all previous test files (600 tokens) ❌ You have test history
- Write verbose explanations (400 tokens) ❌ User doesn't need this
- Build module while explaining (1500 tokens) ❌ Build, then report results
= Wasted 2300+ tokens
```

---

## MASTER APPROVAL RULES (Claude Decides Automatically)

| Decision | Rule | Example |
|----------|------|---------|
| Code implementation | Follow spec exactly | "Build India Storage to match Phase 1 design" → build it |
| Test writing | Write comprehensive tests | "Write tests for edge cases" → always yes |
| Bug fixes | Fix to spec | "Fix import error" → fix it |
| Risk rules | DO NOT CHANGE. Use spec | "Should max risk be 2%?" → use AAATS_MASTER_BLUEPRINT.md value (1.5%) |
| Architecture | DO NOT CHANGE. Use spec | "Should we add new market?" → only if user requests |
| Credentials | NEVER touch .env | "Add API key to .env?" → no, user does this |
| Backtest model | Use spec | "What cost model?" → use AAATS_MASTER_BLUEPRINT.md |

---

## How This File Works

- **Read this file once** at the start of EVERY session
- **Reference SESSION_STATE.md** to know exactly where to resume
- **Follow the BUILD SEQUENCE** — phases are cumulative, don't skip
- **Use the decision framework** to approve/reject changes without asking
- **Update SESSION_STATE.md frequently** so next session picks up seamlessly
- **Stop when token limit approaches** — save state, exit gracefully

---

## Questions?

If clarification needed on any rule:
1. Check MASTER_AUTODRIVER.md (architecture rules)
2. Check AAATS_MASTER_BLUEPRINT.md (design specs)
3. Check AUTONOMOUS_BUILD.md (execution rules, this file)
4. If still unclear: ask user (1-line question only, minimize tokens)

---

**This file is the source of truth for autonomous execution. Update it only if user explicitly requests.**
