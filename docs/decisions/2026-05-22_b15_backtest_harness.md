# Phase B.1.5 — Backtest harness (insert before B.2)

**Status:** PROPOSED — adds a phase to [`2026-05-22_live_flip_rebuild_plan.md`](2026-05-22_live_flip_rebuild_plan.md) Track B.
**Authored:** 2026-05-22 (Cowork session, post session-2 ship report).
**Premise:** B.2 parameter sweeps need somewhere to run. Today's only option is paper-shadow, which costs 4 calendar weeks per sweep iteration. A minimal replay engine pays for itself on the FIRST sweep and compounds for every future strategy decision.

## Why this exists

The current Track B sequence is B.0 → B.0.5 → B.1 → B.2 → B.3. B.2's spec assumes there's a way to run a param sweep:

> **Phase B.2 — Parameter sweeps on tune candidates**
> Scope: for each PARAM-TUNE strategy from B.1, run a sweep against the paper-shadow path (backtest harness if extant; paper-shadow otherwise).

Reality check via `Glob **/backtest*.py` on 2026-05-22: **no backtest harness exists**. Paper-shadow takes ≥7 days per config to produce a meaningful signal. C3 has at least three orthogonal tune dimensions (BTC_DOM_FAST_RISE threshold, symbol deny-list, exit-trigger params), implying ≥9 sweep configs minimum. That's 9+ × 7d = 63+ calendar days of paper-shadow for C3 alone — longer than the entire remaining rebuild sprint.

A replay engine cuts this from 63 days to <1 hour of compute, and unlocks future strategy work (any post-D.5 strategy added has to clear backtest validation before it gets a live capital allocation).

## Phase B.1.5 — Scope

### Files touched

- New `tools/backtest/__init__.py`
- New `tools/backtest/replay_engine.py` — core: iterate historical bars, call `strategy._entry_allowed(ctx)` / `strategy._exit_allowed(ctx)`, track positions, compute P&L.
- New `tools/backtest/historical_data.py` — fetch + cache OHLCV bars from the exchange used by paper-mode (Binance International public REST is free, no auth needed for historical klines).
- New `tools/backtest/sweep_runner.py` — given a base strategy + a dict of `{param_name: [values]}`, runs all combinations, returns a DataFrame of results.
- New `tests/test_backtest_replay.py` — replay against a fixed paper-trades fixture and assert match within tolerance on at least 10 trades.

### Constraints

- **Same strategy code path as production.** The replay engine imports the strategy module directly and calls the same `_entry_allowed` / `_exit_allowed` / `_size_position` functions paper-mode calls. No re-implementation of strategy logic; that's the bug source.
- **Bar resolution = production resolution.** AAATS paper-mode reads 5-minute bars (verify from `markets/` or `trading/live_paper_runner.py`); replay uses the same.
- **No look-ahead.** The replay loop must call strategy functions with only the data that was available at bar `t`, never `t+1`.
- **Fee + slippage assumption.** Use the same constants paper-mode uses (greppable from `execution/paper_trader.py`). If a constant is wrong, fix it once; both paper and backtest pick up the fix.

### Exit criteria

- 10-trade replay fixture: replay engine reproduces paper-mode P&L within ±2¢ per trade.
- `sweep_runner.py` can run 100 param configs in under 10 minutes on the workstation.
- The output DataFrame has columns: `config_hash, total_pnl, win_rate, max_drawdown, n_trades, sharpe, profit_factor`.

### Estimate

1–2 Claude Code sessions. Sub-task-friendly:
- Session a: replay engine + historical data fetcher + fixture-based test (90% of the work).
- Session b: sweep runner + result aggregation + first C3 sweep (low risk if session-a passed).

If session-a runs long, the replay engine alone is enough to unblock B.2 manual param sweeps. Session-b's sweep_runner is operator ergonomics, not a blocker.

### Dependencies

- B.1 triage merged (done, session 2).
- Production fee + slippage constants greppable from a single source.

### Risks

1. **Strategy code has hidden production-only dependencies** (e.g., a function that queries the live DB or hits an API). Mitigation: import the strategy in isolation first, run it on a synthetic bar dict, fix any side-effects by injecting a minimal market-data interface. This may require small refactors in `trading/altcoin_reversion.py` to make `_entry_allowed` a pure function. Risk-budget: half a session.
2. **Historical data gaps** for the C3 symbol universe. Binance has been listed all 32 symbols for the relevant window per spot-check; if any are missing, exclude them from the sweep and document.
3. **The replay drifts from paper-mode** beyond the ±2¢ tolerance. Most likely cause: a feature flag or env var that's read differently in paper vs replay. Mitigation: the replay engine reads the same `.env` as paper-mode in one mode (`--match-paper-env`), and a dedicated `--isolated` mode for parameter sweeps.

## Where this lands in the calendar

- **Track B:** B.0 ✓ → B.0.5 ✓ → B.1 ✓ → **B.1.5 (new, 1-2 sessions)** → B.2 → B.3 (4-week soak).
- **Net calendar impact:** B.2 itself compresses from 1-2 sessions of paper-shadow setup + 4 weeks soak per config (intractable for 9+ configs) down to 1-2 sessions of harness build + hours of compute. **The B.1.5 phase is calendar-neutral or net-positive.**
- **Track C gate (late June 2026):** unchanged. B.3's 4-week soak on the post-tune stack is still the critical path.

## What B.1.5 is NOT

- Not a paper-mode replacement. Paper-mode still runs continuously for live equity-curve evidence.
- Not a strategy-design agent. Operator decides which params to sweep; the harness just executes the sweep.
- Not a live-flip path. Backtest results inform B.1's triage table; they don't unlock C.4 tranche escalation.

## Status log (append-only)

- **2026-05-22** — Phase proposed in Cowork session after operator asked about agent-speed leverage. Pending session 4 or later for execution; session 3 prompt is unchanged (B.2 still scheduled there per original sequencing, but operator can swap session-3 [2] for B.1.5 if preferred).
