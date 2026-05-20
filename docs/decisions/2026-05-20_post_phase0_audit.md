# Post-Phase-0 Strategy Activity Audit — 2026-05-20

Audit recorded at the close of the Phase-0 paper-trading-readiness session.
Three commits shipped this session beyond the two B' commits pushed up front:

| SHA       | Scope                                                    |
|-----------|----------------------------------------------------------|
| 1559876   | docs(audit): G2 HS4 architectural mismatch (was fba2096) |
| fb59128   | refactor(risk): apply_kill_switch_gate helper + C3/C6    |
| 05f4d8f   | ops(rollback): record B' deploy SHAs in MANIFEST         |
| d1b7feb   | fix(risk): halt_on_critical=False -> True (G1)           |
| c9e7172   | feat(runner): CYCLE_SUMMARY observability (OBS)          |

## Enforcement coverage

Every firing strategy in the live runtime is now subject to kill-switch
gating, either through `execute()` or through the shared
`apply_kill_switch_gate()` helper introduced by fb59128:

| Strategy | Path                                                | Kill-switch route              |
|----------|-----------------------------------------------------|--------------------------------|
| C1       | trading/stat_arb.py (BTC/ETH spread)                | via execute() (pre-existing)   |
| C2       | trading/momentum_breakout.py (BTC/ETH 4H breakout)  | via execute() (pre-existing)   |
| C3       | trading/altcoin_reversion.py (mean-reversion scan)  | apply_kill_switch_gate (NEW)   |
| C5b      | trading/funding_arb.py                              | n/a — halted at source         |
| C6       | trading/bollinger_range.py (range trading)          | apply_kill_switch_gate (NEW)   |

`halt_on_critical=True` (d1b7feb) closes the reconciler-driven path: if
`scripts/reconcile_intracycle.reconcile_now` detects critical drift, the
runner now halts the loop instead of logging-and-continuing. Combined with
the helper, this means kill-switch enforcement is live across both:
- Strategy-emit time (the helper checks before BUY/SELL emission), AND
- Reconciler-detection time (the flag fires HALT inside the runner loop).

## Comparison to pre-session baselines

Pre-session (taken at the start of the session):
- C3: 6 positions (SOL/CHZ/XUSD/U/RLUSD/LTC)
- C6: 0 positions
- C3 24h BUY count: 8
- share_equality_mismatches.json: {}

Post-session (captured 2026-05-20T17:54:38Z, cycle 4 of the OBS image):
- C3: 5 positions (CHZ/XUSD/LTC/RLUSD/U) — SOL was sold during the B' soak
  (2026-05-20T14:40:41Z, `reason=z_overshoot z=0.749 pnl=$0.1687 (1.12%)`),
  the kill-switch helper did not block (no halt active), and the SELL went
  through cleanly via execute().
- C6: 0 positions (state file empty, hasn't traded — last mtime 00:27:55+02
  is the file-creation timestamp from a prior run).
- share_equality_mismatches.json: {} — held flat through three deploys.

## Hard-stops triggered this session

None. All three deploys (B' verification, G1, OBS) and all three soaks
(3-cycle, 5-cycle, 2-cycle) ran clean.

## Final state (2026-05-20T17:54:38Z)

- Container image SHA: `sha256:d5f30630754a57d391a799a0f72df1cb3bc81dbbbc2c84f34b7b645c5b0c11f9`
- Box `trading/live_paper_runner.py` SHA: `7d48a501ad2a85f7200a2f0aee4121727a78314e56108a2e6d409b3eda7553dc`
- RestartCount: 0
- Status: running
- Latest CYCLE_SUMMARY emitted:
  `[runner] cycle 4 complete: C1=idle C2=idle C3=hold(5,picks=3) C5b=halted_src C6=idle`

## Banked for Phase 1 (NOT in scope this session)

- BTC/ETH pair-selection review (engine eg_p=0.39)
- C6 scanner correlation_guard cap mis-tuning
- A' literal routing (deferred sprint; only needed if mkt_pos coupling is
  actually required)
- Real capital deployment gates
- Strategy doctrine threshold reviews

## Verification timeline

| Time (UTC)        | Event                                                          |
|-------------------|----------------------------------------------------------------|
| 13:34             | Session start                                                  |
| 14:43             | B' soak SUCCESS (3 cycles 7-9 clean; C3 SELL SOL/USDT inside)  |
| ~15:00            | B' push (origin/main: 05f4d8f) over 193 backlog auto-commits   |
| 15:30             | G1 deploy: halt_on_critical=False -> True                      |
| 17:03             | G1 soak SUCCESS (5 cycles 3-7, no HALT, no exceptions)         |
| ~17:05            | G1 push (origin/main: d1b7feb)                                 |
| 17:08             | OBS deploy: CYCLE_SUMMARY emitter live                         |
| 17:42             | OBS soak SUCCESS (4 cycles caught, 1:1 summary-to-cycle ratio) |
| ~17:55            | OBS push (origin/main: c9e7172)                                |
