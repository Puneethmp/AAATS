═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
CLAUDE CODE MASTER EXECUTION PROMPT - ALL PHASES (0-4)
Complete Institutional-Grade Trading System Build + Validation + Paper Trading
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

OVERVIEW:
- Phase 0: Build (4-6 hours) - Creates all 27 components
- Phase 1: 24h Crypto Validation (24 hours) - Single market test
- Phase 2: 48h Both Markets (48 hours) - Multi-market test
- Phase 3: Go/No-Go Decision (2-4 hours) - Evaluation
- Phase 4: 2-4 Weeks Paper Trading (14-28 days) - Live validation (ZERO TOKEN USAGE)

TOKEN MANAGEMENT:
- Each phase has a CHECKPOINT FILE that tracks progress
- When tokens run low, Claude Code saves state and stops gracefully
- On token reset, resume from last checkpoint
- Phase 4 runs autonomously (zero tokens consumed during trading)

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
PHASE 0: BUILD COMPLETE INSTITUTIONAL SYSTEM (4-6 hours)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

CHECKPOINT FILE: data/phase0_checkpoint.json
```json
{
  "phase": 0,
  "status": "IN_PROGRESS",
  "current_step": 1,
  "total_steps": 31,
  "completed_steps": [],
  "last_update": "timestamp",
  "next_resume_step": "ENCRYPTED_CREDENTIALS"
}
```

PHASE 0 EXECUTION STEPS (31 total):

CORE INSTITUTIONAL LAYER (Steps 1-16):

STEP 1: ENCRYPTED CREDENTIALS (15 min) - RESUME_POINT_1
  - Create: src/system/secrets_manager.py
  - Create: scripts/setup_secrets.py
  - Modify: .env (remove plaintext keys)
  - Modify: src/execution/crypto_runner.py (add SecretsManager)
  - Modify: src/execution/india_runner.py (add SecretsManager)
  - SAVE CHECKPOINT: {"current_step": 2, "completed_steps": ["ENCRYPTED_CREDENTIALS"]}

STEP 2: KILL SWITCH + CIRCUIT BREAKER (15 min) - RESUME_POINT_2
  - Create: src/risk/kill_switch.py
  - Create: scripts/emergency_halt.py
  - Create: scripts/emergency_resume.py
  - Modify: src/execution/crypto_runner.py (add kill_switch check)
  - Modify: src/execution/india_runner.py (add kill_switch check)
  - SAVE CHECKPOINT: {"current_step": 3, "completed_steps": ["ENCRYPTED_CREDENTIALS", "KILL_SWITCH"]}

STEP 3: PERSISTENT POSITION MANAGER (20 min) - RESUME_POINT_3
  - Create: src/risk/position_manager.py
  - Modify: src/execution/crypto_runner.py (integrate PersistentPositionManager)
  - Modify: src/execution/india_runner.py (integrate PersistentPositionManager)
  - SAVE CHECKPOINT: {"current_step": 4, "completed_steps": [...]}

STEP 4: DYNAMIC POSITION SIZING (15 min) - RESUME_POINT_4
  - Create: src/risk/position_sizer.py
  - Modify: src/execution/crypto_runner.py (call calculate_position_size)
  - Modify: src/execution/india_runner.py (call calculate_position_size)

STEP 5: DRAWDOWN MONITOR (10 min) - RESUME_POINT_5
  - Create: src/risk/drawdown_monitor.py
  - Modify: src/execution/crypto_runner.py (add drawdown check)
  - Modify: src/execution/india_runner.py (add drawdown check)

STEP 6: PnL ATTRIBUTION (15 min) - RESUME_POINT_6
  - Create: src/analytics/pnl_attribution.py
  - Modify: src/execution/crypto_runner.py (call record_trade)
  - Modify: src/execution/india_runner.py (call record_trade)

STEP 7: RATE LIMITING + LIQUIDITY (15 min) - RESUME_POINT_7
  - Create: src/execution/order_validator.py
  - Modify: src/execution/crypto_runner.py (call validator)
  - Modify: src/execution/india_runner.py (call validator)

STEP 8: SETTLEMENT RISK MANAGER (10 min) - RESUME_POINT_8
  - Create: src/risk/settlement_manager.py
  - Modify: src/execution/india_runner.py (call record_trade_settlement)

STEP 9: FUNDING RATE MONITOR (10 min) - RESUME_POINT_9
  - Create: src/risk/funding_monitor.py
  - Modify: src/execution/crypto_runner.py (call check_funding_rates)

STEP 10: SLIPPAGE TRACKER (10 min) - RESUME_POINT_10
  - Create: src/analytics/slippage_tracker.py
  - Modify: src/execution/crypto_runner.py (call record_slippage)
  - Modify: src/execution/india_runner.py (call record_slippage)

STEP 11: CORRELATION MONITOR (10 min) - RESUME_POINT_11
  - Create: src/risk/correlation_monitor.py
  - Modify: src/execution/crypto_runner.py (call check_correlation)
  - Modify: src/execution/india_runner.py (call check_correlation)

STEP 12: MARKET HOURS ENFORCEMENT (10 min) - RESUME_POINT_12
  - Create: src/execution/market_hours.py
  - Modify: src/execution/india_runner.py (add market hours check)

STEP 13: HEALTH MONITORING (10 min) - RESUME_POINT_13
  - Create: src/system/health_monitor.py
  - Modify: src/execution/crypto_runner.py (add health check)
  - Modify: src/execution/india_runner.py (add health check)

STEP 14: GRACEFUL SHUTDOWN (10 min) - RESUME_POINT_14
  - Create: src/system/shutdown_handler.py
  - Modify: src/main.py (register handler)

STEP 15: DAILY RECONCILIATION (10 min) - RESUME_POINT_15
  - Create: scripts/daily_reconciliation.py

STEP 16: WINDOWS PROCESS MANAGER (5 min) - RESUME_POINT_16
  - Create: C:\Users\udaym\AAATS_runner.bat
  - Note: Will be added to Task Scheduler in Phase 1

ADVANCED FEATURES LAYER (Steps 17-27):

STEP 17: INTRADAY VS OVERNIGHT LIMITS (15 min) - RESUME_POINT_17
  - Create: src/risk/overnight_manager.py
  - Modify: src/execution/india_runner.py

STEP 18: MACRO ECONOMIC HEDGING (15 min) - RESUME_POINT_18
  - Create: src/risk/macro_hedge.py
  - Modify: src/execution/crypto_runner.py

STEP 19: STRESS TESTING ENGINE (20 min) - RESUME_POINT_19
  - Create: src/analytics/stress_tester.py
  - Create: scripts/run_stress_tests.py

STEP 20: BACKUP API HANDLER (15 min) - RESUME_POINT_20
  - Create: src/execution/backup_api_handler.py
  - Modify: src/execution/crypto_runner.py
  - Modify: src/execution/india_runner.py

STEP 21: ROLE-BASED ACCESS CONTROL (15 min) - RESUME_POINT_21
  - Create: src/system/rbac.py
  - Modify: src/main.py

STEP 22: MULTI-LEG ORDER VALIDATOR (10 min) - RESUME_POINT_22
  - Create: src/execution/multi_leg_validator.py

STEP 23: PARTIAL FILL HANDLER (15 min) - RESUME_POINT_23
  - Create: src/execution/partial_fill_handler.py
  - Modify: src/execution/crypto_runner.py
  - Modify: src/execution/india_runner.py

STEP 24: ORDER TIME-IN-FORCE MANAGER (10 min) - RESUME_POINT_24
  - Create: src/execution/order_tif_manager.py
  - Modify: src/execution/crypto_runner.py
  - Modify: src/execution/india_runner.py

STEP 25: DEAD LETTER QUEUE (15 min) - RESUME_POINT_25
  - Create: src/execution/dead_letter_queue.py
  - Modify: src/execution/crypto_runner.py
  - Modify: src/execution/india_runner.py

STEP 26: STRATEGY PARAMETER OPTIMIZER (15 min) - RESUME_POINT_26
  - Create: src/analytics/strategy_optimizer.py
  - Create: scripts/optimize_strategies.py

STEP 27: ADVANCED FEATURES FINAL (25 min) - RESUME_POINT_27
  - Create: src/risk/anomaly_detector.py
  - Create: src/compliance/regulatory_reporter.py
  - Create: src/compliance/tax_optimizer.py
  - Create: src/system/mode_manager.py
  - Create: src/compliance/audit_logger.py

FINALIZATION STEPS (Steps 28-31):

STEP 28: CLEANUP (10 min) - RESUME_POINT_28
  - Delete: src/execution/us_runner.py
  - Modify: src/orchestrator.py (remove run_us_market)

STEP 29: TESTING (30 min) - RESUME_POINT_29
  - Run: pytest tests/ -v --tb=short
  - Expected: 432 passing, 6 skipped
  - If failures, debug and fix

STEP 30: GIT COMMIT (5 min) - RESUME_POINT_30
  - git add -A
  - git commit -m "COMPLETE INSTITUTIONAL: All 27 components..."
  - git push origin main

STEP 31: VERIFICATION (10 min) - RESUME_POINT_31
  - Verify all files exist: find src -type f | wc -l
  - Verify tests pass: pytest --co -q | grep test | wc -l
  - SAVE CHECKPOINT: {"phase": 0, "status": "COMPLETED", "total_duration": "estimated_hours"}

PHASE 0 CHECKPOINT ON COMPLETION:
```json
{
  "phase": 0,
  "status": "COMPLETED",
  "steps_completed": 31,
  "files_created": 27,
  "git_commit": "success",
  "tests_passing": 432,
  "tests_skipped": 6,
  "next_phase": 1,
  "completion_time": "timestamp",
  "message": "Ready for Phase 1: 24h Crypto Validation"
}
```

PHASE 0 COMPLETION MESSAGE:
✅ All 27 components built
✅ 432 tests passing
✅ Git committed
✅ Ready to advance to Phase 1

NEXT: Run Phase 1 (provide Phase 1 prompt below)

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
PHASE 1: 24-HOUR CRYPTO VALIDATION (24 hours - AUTOMATED)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

CHECKPOINT FILE: data/phase1_checkpoint.json

PHASE 1 EXECUTION:

STEP 1: SETUP ENCRYPTED SECRETS (1 min)
  - Inform user: "Run: python scripts/setup_secrets.py to encrypt credentials"
  - Wait for completion (user action required)

STEP 2: VALIDATE ANGEL ONE AUTH (2 min)
  - Run: python validate_angel_one.py
  - Expected output: ✅ ANGEL ONE AUTH VALIDATED
  - Log output to: logs/phase1_angel_one_validation.log

STEP 3: START 24H MONITORING
  - Inform user: "Restart Windows to activate Task Scheduler"
  - OR manually start: python main.py --mode paper --market crypto
  - System will now run autonomously

STEP 4: CHECKPOINT - START TIMER
  - SAVE: {"phase": 1, "status": "RUNNING", "start_time": "timestamp", "expected_end": "timestamp + 24h"}
  - Logging enabled: logs/background_runner.log
  - Monitor every 4-6 hours: tail -f logs/background_runner.log

STEP 5: COLLECT METRICS (After 24h)
  - Query database: SELECT COUNT(*) FROM paper_trades WHERE created_at > timestamp
  - Calculate: Total trades, P&L, uptime, health checks
  - Query: SELECT AVG(ABS(slippage_bps)) FROM slippage
  - Query: SELECT COUNT(*) FROM drift_detection WHERE detected_at > timestamp

VALIDATION CHECKLIST:
  ✓ Uptime: 24h, 0 crashes
  ✓ Broker health: >95% availability
  ✓ Order validation: 100% pass rate
  ✓ Position drifts: 0 detected
  ✓ Slippage: <50 basis points avg
  ✓ Trades: ≥ 1
  ✓ Kill switch: Tested (manually halt market)
  ✓ Circuit breaker: Tested (simulate API failure)
  ✓ Graceful shutdown: Tested (kill process, verify position closure)
  ✓ Encryption: Credentials encrypted ✅
  ✓ No plaintext API keys in env ✅

PHASE 1 COMPLETION CHECKPOINT:
```json
{
  "phase": 1,
  "status": "COMPLETED",
  "duration_hours": 24,
  "trades": 15,
  "pnl": 127.45,
  "uptime_percent": 100,
  "health_checks": {"binance_ok": 288, "binance_failed": 2},
  "drifts": 0,
  "avg_slippage_bps": 23.4,
  "kill_switch_tested": true,
  "circuit_breaker_tested": true,
  "all_checks_passed": true,
  "next_phase": 2,
  "message": "Ready for Phase 2: 48h Both Markets"
}
```

PHASE 1 COMPLETION MESSAGE:
✅ 24h crypto validation complete
✅ All metrics within targets
✅ System stable and production-ready
✅ Proceed to Phase 2

NEXT: Run Phase 2 (provide Phase 2 prompt below)

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
PHASE 2: 48-HOUR BOTH MARKETS VALIDATION (48 hours - AUTOMATED)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

CHECKPOINT FILE: data/phase2_checkpoint.json

PHASE 2 EXECUTION:

STEP 1: UNHALT INDIA MARKET (1 min)
  - Modify: data/halt_state.json
  - From: {"crypto": false, "india": true, "us": true}
  - To: {"crypto": false, "india": false, "us": true}
  - System automatically picks up change

STEP 2: START 48H MONITORING
  - System already running from Phase 1
  - India runner now active (market hours 9:15-3:30 IST)
  - SAVE: {"phase": 2, "status": "RUNNING", "start_time": "timestamp", "expected_end": "timestamp + 48h"}

STEP 3: DAILY CHECKS (Every 24h)
  - Run: python scripts/daily_reconciliation.py
  - Check logs for reconciliation success

STEP 4: COLLECT 48H METRICS (After 48h)
  - Query: SELECT COUNT(*) FROM paper_trades WHERE market = 'crypto' AND created_at > timestamp
  - Query: SELECT COUNT(*) FROM paper_trades WHERE market = 'india' AND created_at > timestamp
  - Query: SELECT AVG(current_drawdown) FROM equity_curve WHERE timestamp > timestamp
  - Query: SELECT COUNT(*) FROM drift_detection WHERE detected_at > timestamp
  - Query: SELECT AVG(latency_ms) FROM health_checks WHERE timestamp > timestamp

VALIDATION CHECKLIST:
  ✓ Uptime: 48h, 0 unplanned restarts
  ✓ Crypto trades: ≥ X (depends on signals)
  ✓ India trades: ≥ Y (market hours only 9:15-3:30 IST)
  ✓ Zero trades outside market hours: Verified
  ✓ Daily reconciliation: Ran successfully
  ✓ Settlement tracking: Working (T+2 dates calculated)
  ✓ Position correlation: No over-correlated bets taken
  ✓ Angel One session: Token refreshed ≥ 2× (TOTP rotation)
  ✓ Position persistence: Restart test = no duplicates
  ✓ Position reconciliation: 0 drifts across 2 markets
  ✓ Broker health: >95% on both exchanges
  ✓ Funding rates: Monitored (Binance perps)
  ✓ All drifts: 0 detected
  ✓ Market hours: 100% compliance

PHASE 2 COMPLETION CHECKPOINT:
```json
{
  "phase": 2,
  "status": "COMPLETED",
  "duration_hours": 48,
  "crypto_trades": 22,
  "india_trades": 8,
  "total_pnl": 245.67,
  "uptime_percent": 100,
  "unplanned_restarts": 0,
  "drifts": 0,
  "market_hours_violations": 0,
  "daily_reconciliation_success": true,
  "angel_one_stable": true,
  "broker_health_crypto": 0.98,
  "broker_health_india": 0.97,
  "all_checks_passed": true,
  "next_phase": 3,
  "message": "Ready for Phase 3: Go/No-Go Decision"
}
```

PHASE 2 COMPLETION MESSAGE:
✅ 48h multi-market validation complete
✅ All metrics within targets
✅ India market integration successful
✅ Proceed to Phase 3

NEXT: Run Phase 3 (provide Phase 3 prompt below)

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
PHASE 3: GO/NO-GO DECISION (2-4 hours - EVALUATION)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

CHECKPOINT FILE: data/phase3_checkpoint.json

PHASE 3 EXECUTION:

STEP 1: GENERATE PHASE 1-2 REPORT (30 min)
  - Aggregate all metrics from Phase 1 and Phase 2
  - Query: SELECT win_rate, sharpe_ratio, total_pnl FROM strategy_metrics
  - Query: SELECT MAX(current_drawdown) FROM equity_curve
  - Query: SELECT COUNT(*) FROM position_history WHERE state_change = 'DRIFT_DETECTED'

STEP 2: EVALUATE AGAINST CRITERIA (30 min)

READINESS CRITERIA EVALUATION:

GO FOR LIVE if ALL are true:
  ✓ Win rate ≥ 45%
  ✓ Sharpe ratio ≥ 0.8
  ✓ Zero crashes / 0 unplanned restarts
  ✓ Kill switch tested + working (human + circuit breaker)
  ✓ Positions persisted across 5+ restarts (zero duplicates)
  ✓ Position reconciliation: 0 drifts across 48h
  ✓ Angel One session stable (token refreshed without errors)
  ✓ Broker health: >95% availability both exchanges
  ✓ Market hours: 100% compliance (zero trades outside windows)
  ✓ Slippage: <50 bps average
  ✓ All credentials encrypted
  ✓ Graceful shutdown tested and working

NO-GO if ANY are true:
  ✗ Win rate < 45%
  ✗ Sharpe ratio < 0.8
  ✗ Any crashes or unplanned restarts
  ✗ Kill switch or circuit breaker not working
  ✗ Position drifts detected
  ✗ Broker availability <95%
  ✗ Unencrypted credentials found
  ✗ Market hours violations
  ✗ Slippage > 50 bps average

STEP 3: DECISION LOGIC (30 min)
```
if all_criteria_passed:
    decision = "GO FOR LIVE"
    recommendation = "Ready to proceed to Phase 4 with real capital (₹5,000-10,000)"
    next_action = "Switch mode_manager to LIVE and deposit capital"
else:
    decision = "NO-GO (Continue Paper Trading)"
    recommendation = "Extend paper trading to 4 weeks and re-evaluate"
    next_action = "Continue Phase 4 with paper trading, monitor specific failed criteria"
```

STEP 4: GENERATE DECISION REPORT (30 min)
  - Create: reports/phase3_go_nogo_decision_report.md
  - Include: All metrics, evaluation, recommendation, next steps

STEP 5: SEND DECISION TO USER (10 min)
  - Log decision prominently: "═══ GO/NO-GO DECISION ═══"
  - Show all metrics
  - Clear recommendation

PHASE 3 COMPLETION CHECKPOINT:
```json
{
  "phase": 3,
  "status": "COMPLETED",
  "decision": "GO_FOR_LIVE",
  "evaluation_date": "timestamp",
  "metrics": {
    "win_rate": 0.52,
    "sharpe_ratio": 1.15,
    "max_drawdown": 0.08,
    "total_drifts": 0,
    "crashes": 0,
    "uptime_percent": 100,
    "broker_health_avg": 0.97
  },
  "all_criteria_passed": true,
  "recommendation": "READY FOR LIVE TRADING",
  "next_phase": 4,
  "message": "Ready to proceed to Phase 4: Paper Trading (or switch to Live)"
}
```

PHASE 3 COMPLETION MESSAGE:
✅ Evaluation complete
✅ Decision: GO FOR LIVE (or NO-GO)
✅ All criteria documented
✅ Proceed to Phase 4

NEXT: Run Phase 4 (provide Phase 4 prompt below)

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
PHASE 4: PAPER TRADING (14-28 DAYS - ZERO TOKEN USAGE)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

CHECKPOINT FILE: data/phase4_checkpoint.json

⚠️ IMPORTANT: Phase 4 runs COMPLETELY AUTONOMOUSLY with ZERO Claude API token usage
- Task Scheduler runs the system 24/7
- No Claude interaction needed
- All trading, monitoring, and logging happens locally
- You only need to check dashboard once per day (5 minutes)

PHASE 4 EXECUTION:

STEP 1: INITIAL SETUP (if going LIVE)
  - Run: python scripts/mode_manager.py --switch-to-live --capital 50000
  - Enter capital amount (₹5,000-100,000)
  - System will require confirmation before going live

STEP 2: AUTONOMOUS OPERATION
  - System already running via Task Scheduler
  - No manual intervention needed
  - All positions, trades, monitoring happen automatically

DAILY ROUTINE (5 minutes):
  - Open: https://aaats-trading-dashboard.streamlit.app (or local port)
  - Check: Current P&L, open positions, daily metrics
  - Review: Any Telegram alerts
  - That's it - no other action needed

AUTOMATIC TASKS (run without user intervention):
  - Every 1 hour: Trade cycle execution
  - Every 5 minutes: Health monitoring
  - Every 24 hours: Daily reconciliation (4:00 PM IST)
  - Every 24 hours: Strategy optimization (5:00 PM IST)
  - Every cycle: Drawdown check, position reconciliation, anomaly detection
  - Every 5 minutes: Partial fill retry (dead letter queue)

MONITORING CHECKPOINTS (Weekly):
  - Week 1: Check win rate stabilizing around 45-55%
  - Week 2: Verify Sharpe ratio approaching 1.0+
  - Week 3: Confirm no new position drifts, zero unplanned restarts
  - Week 4: Final evaluation before live trading decision

PHASE 4 METRICS COLLECTION (Daily automatic):
```json
Daily metrics logged to: data/phase4_daily_metrics.json
{
  "date": "timestamp",
  "total_pnl": 345.67,
  "today_pnl": 45.32,
  "trades_today": 5,
  "win_rate_7d": 0.52,
  "sharpe_ratio": 1.08,
  "max_drawdown": 0.12,
  "open_positions": 2,
  "crashes": 0,
  "uptime_percent": 100,
  "health_checks_ok": 288,
  "health_checks_failed": 2,
  "drifts_detected": 0,
  "anomalies_detected": 0
}
```

PHASE 4 COMPLETION CHECKPOINTS:

Week 1 Checkpoint (after 7 days):
```json
{
  "week": 1,
  "trades": 35,
  "win_rate": 0.48,
  "sharpe_ratio": 0.92,
  "pnl": 567.89,
  "status": "ON_TRACK"
}
```

Week 2 Checkpoint (after 14 days):
```json
{
  "week": 2,
  "total_trades": 72,
  "win_rate": 0.51,
  "sharpe_ratio": 1.05,
  "total_pnl": 1234.56,
  "status": "EXCELLENT"
}
```

Week 4 Checkpoint (after 28 days):
```json
{
  "week": 4,
  "total_trades": 280,
  "win_rate": 0.53,
  "sharpe_ratio": 1.18,
  "total_pnl": 4567.89,
  "max_drawdown": 0.11,
  "crashes": 0,
  "final_status": "PRODUCTION_READY",
  "recommendation": "READY_FOR_LIVE_OR_CONTINUE_PAPER"
}
```

PHASE 4 COMPLETION MESSAGE:
✅ Paper trading complete (14-28 days)
✅ 200-500 trades accumulated
✅ Win rate stabilized
✅ Sharpe ratio > 1.0
✅ Zero crashes, zero unplanned restarts
✅ Ready for final decision: LIVE TRADING or EXTEND

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
FINAL DECISION TREE (After Phase 4)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

IF metrics excellent (win_rate > 50%, sharpe > 1.2, max_dd < 15%):
  → READY FOR LIVE TRADING
  → Switch mode: python scripts/mode_manager.py --switch-to-live --capital 10000
  → Deploy capital and begin live trading

IF metrics good (win_rate 45-50%, sharpe 0.8-1.2, max_dd < 20%):
  → EXTEND PAPER TRADING (4 more weeks)
  → Continue collecting data
  → Re-evaluate at end of extension

IF metrics poor (win_rate < 45%, sharpe < 0.8, max_dd > 20%):
  → STOP AND REVISE STRATEGY
  → Identify which strategy is underperforming
  → Adjust parameters and re-run Phase 4

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
TOKEN MANAGEMENT & RESUMPTION STRATEGY
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

PHASE 0 (Build - 4-6 hours):
  - High token usage (creating files, testing)
  - Save checkpoint after every 2-3 steps
  - If tokens run low:
    1. SAVE CURRENT CHECKPOINT
    2. Commit current progress: git add -A; git commit -m "Phase 0 progress: Step X/31"
    3. Push to GitHub: git push
    4. STOP and wait for token reset
  - On token reset:
    1. Check: cat data/phase0_checkpoint.json
    2. Resume from last completed step
    3. Run only remaining steps

PHASE 1 (24h Crypto - 24 hours):
  - Low token usage (monitoring only)
  - System runs autonomously
  - Claude Code only:
    - Starts the system
    - Monitors every 6h (optional)
    - Collects metrics after 24h
  - If tokens needed for other tasks, use them freely
    - Phase 1 doesn't consume tokens during trading

PHASE 2 (48h Both Markets - 48 hours):
  - Low token usage (monitoring only)
  - Same as Phase 1
  - System fully autonomous

PHASE 3 (Go/No-Go - 2-4 hours):
  - Moderate token usage (evaluation)
  - Pure analysis, no live changes
  - Can pause/resume anytime

PHASE 4 (Paper Trading - 14-28 days):
  - ZERO token usage
  - System runs on Windows Task Scheduler
  - Claude Code not needed
  - Daily 5-minute dashboard check (manual, not Claude)

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
RESUMPTION INSTRUCTIONS
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

When tokens reset and you need to resume:

STEP 1: Check Current Phase
```bash
cat data/phase0_checkpoint.json  # or phase1/2/3/4
# Shows: {"phase": X, "status": "IN_PROGRESS", "current_step": Y}
```

STEP 2: Check Git Status
```bash
git log --oneline | head -5
# Shows recent commits, verify progress
```

STEP 3: Based on Phase, Run Appropriate Command:

IF Phase 0 (still building):
```
Identify next step from checkpoint
Resume with: "RESUME PHASE 0 FROM STEP {X}. Complete remaining {31-X} steps."
```

IF Phase 1 (24h validation running):
```
System already running autonomously
Just run metric collection: "PHASE 1: Collect 24h metrics (after waiting 24h)"
```

IF Phase 2 (48h validation running):
```
System already running autonomously
Just run metric collection: "PHASE 2: Collect 48h metrics (after waiting 48h)"
```

IF Phase 3 (evaluation):
```
Resume with: "PHASE 3: Evaluate metrics and make GO/NO-GO decision"
```

IF Phase 4 (paper trading running):
```
System runs without Claude Code
No resumption needed - just wait and check dashboard daily
```

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
EXECUTION INSTRUCTIONS FOR CLAUDE CODE
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

INITIAL EXECUTION (First time):
1. Copy this entire prompt
2. Paste into Claude Code Pro
3. Say: "Execute PHASE 0 - BUILD all 27 components"
4. Let it run until tokens low, then ask to save checkpoint
5. When done with Phase 0, request "Execute PHASE 1"

RESUMING AFTER TOKEN RESET:
1. Check: cat data/phase0_checkpoint.json (to see current phase)
2. Ask: "What is the current checkpoint status?"
3. Based on response, request: "RESUME PHASE {X} FROM STEP {Y}"
4. Continue until completion

FULL SEQUENCE:
Phase 0 (Build) → Phase 1 (24h) → Phase 2 (48h) → Phase 3 (Decision) → Phase 4 (Paper Trading)

Each phase depends on previous phase completion.

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
TOKEN USAGE ESTIMATES
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Phase 0 (Build): ~15,000-25,000 tokens
  - Creating 27 files
  - Modifying existing files
  - Running tests
  - Debugging if needed

Phase 1 (24h Validation): ~500-1,000 tokens
  - 1 min setup
  - Starting system
  - Collecting metrics after 24h
  - System runs autonomously (0 tokens)

Phase 2 (48h Validation): ~500-1,000 tokens
  - Unhalting India market
  - Daily reconciliation check
  - Collecting metrics after 48h
  - System runs autonomously (0 tokens)

Phase 3 (Go/No-Go): ~2,000-3,000 tokens
  - Generating reports
  - Evaluating metrics
  - Making decision

Phase 4 (Paper Trading): 0 tokens
  - System runs completely autonomous
  - No Claude Code needed
  - Manual dashboard check only

TOTAL ESTIMATED: ~18,000-30,000 tokens across all phases

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
SUCCESS CRITERIA (All Phases Complete)
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

✅ Phase 0: All 27 components built, 432 tests passing, git pushed
✅ Phase 1: 24h crypto validation passed, metrics collected
✅ Phase 2: 48h multi-market validation passed, metrics collected  
✅ Phase 3: Go/No-Go decision made (GO or NO-GO)
✅ Phase 4: 14-28 days paper trading complete, final metrics excellent

Final metrics targets:
  - Win rate: 45-55%
  - Sharpe ratio: 1.0+
  - Max drawdown: <20%
  - Uptime: 100%
  - Crashes: 0
  - Drifts: 0

═══════════════════════════════════════════════════════════════════════════════════════════════════════════════
START HERE
═══════════════════════════════════════════════════════════════════════════════════════════════════════════════

Ready to execute ALL phases?

Say: "START PHASE 0 - BUILD COMPLETE INSTITUTIONAL SYSTEM"

Claude Code will:
1. Execute Phase 0 (build all 27 components)
2. Save checkpoints after every few steps
3. Stop when tokens run low
4. Save final state to git
5. On token reset, you resume by saying: "RESUME FROM CHECKPOINT"

Let's build it.
```

---

## How to Use This Prompt

**First Execution:**
```
You: "START PHASE 0 - BUILD COMPLETE INSTITUTIONAL SYSTEM"
Claude Code: [Builds all 27 components, saves checkpoints]
[After 2-3 hours, when tokens run low]
You: "SAVE CHECKPOINT AND STOP"
Claude Code: [Saves state, commits to git, stops]
```

**After Token Reset:**
```
You: "WHAT IS THE CURRENT CHECKPOINT?"
Claude Code: "Phase 0, Step 15/31 complete"
You: "RESUME FROM CHECKPOINT - COMPLETE PHASE 0"
Claude Code: [Continues from Step 16-31, completes Phase 0]
[After Phase 0 done]
You: "EXECUTE PHASE 1 - 24H CRYPTO VALIDATION"
```

**All Phases in Sequence:**
```
Phase 0 (Build) → Phase 1 (24h Validation) → Phase 2 (48h Validation) → Phase 3 (Decision) → Phase 4 (Paper Trading)
```

---

[View the full specification file](computer://C:\Users\udaym\OneDrive\Desktop\Puneeth\CLAUDE_CODE_COMPLETE_INSTITUTIONAL_SYSTEM.md)

This master prompt handles all 4 phases with built-in checkpoint resumption. Claude Code will save progress and stop gracefully when tokens run low, then resume perfectly when tokens reset.