"""tools/backtest - B.1.5 minimal replay engine for C3 / future strategies.

Spec: docs/decisions/2026-05-22_b15_backtest_harness.md
Session-9 contract: docs/decisions/2026-05-22_live_flip_rebuild_plan.md Track E.

Coverage today (session 9): C3 altcoin_reversion only. Reimplements the
entry/exit driver in tools/backtest/c3_replay.py using C3's pure-function
components (_compute_z_score / _rsi / _realized_daily_vol / _compute_trade_size).
The strategy module's run_altcoin_reversion_crypto() is intentionally NOT
called by the replay engine - that path is tightly coupled to wall-clock
time, file-system state, and DB writes, none of which are appropriate in a
historical replay.

What the replay engine does NOT cover (documented limitations, surfaced in
the `evidence` paragraph of each recommendation):
  - HMM regime classification (replay assumes RANGE_BOUND throughout, which
    is the C3-entry-permissive choice; BEAR would block all entries).
  - BTC.D fast-rise filter (replay disables; conservative=permissive choice).
  - ML gate (C3 has no ML gate per source comment).
  - Operator/engine halts (no halt in replay).
  - Reconciler / dust filter (no DB in replay).

These limitations make the backtest a PERMISSIVE upper bound. A NO-GO
verdict from the harness therefore means the strategy is unprofitable even
under best-case conditions; a GO/PARTIAL verdict means it is profitable
under best-case conditions but live results may underperform.
"""
