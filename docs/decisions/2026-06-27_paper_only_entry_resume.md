# Decision — time-boxed PAPER-ONLY entry resume (observation)

**Date:** 2026-06-27
**Status:** ACTIVE (7-day window; box auto-reverts at the deadline)
**Change class:** operator-authorized exception to the ENTRIES_DISABLED posture —
**observation only, paper-only, time-boxed. NOT a strategy reopen.**
**Authorization:** Puneeth (operator), explicit and detailed.

## What this is — and what it is NOT

The operator authorized a bounded, **PAPER-ONLY** exception to the maintenance
contract's entries-disabled posture, purely to **watch the simulated bot place
paper trades again** for a fixed window, then auto-revert.

This is **NOT**:
- a reactivation of the directional-crypto edge program,
- a reopening of the strategy hunt,
- a new pre-registered thesis.

**The 36-month / 15-fold walk-forward NO-GO stands unchanged**
([2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md](2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md)).
The existing C1/C3/C6 stack has **no proven edge**; nothing here changes that.
Any paper PnL in this window is observational noise, not evidence of an edge.

## Paper-only isolation (gates proven before any change)

1. **Only change = paper crypto entries.** The gate is the module constant
   `ENTRIES_DISABLED` in `trading/{live_paper_runner,stat_arb,altcoin_reversion,
   bollinger_range}.py` (flipped `True`→`False`). BUYs route to
   `execution.paper_trader.record_trade()` — simulated.
2. **Paper engine, no live path.** Container `aaats-paper-crypto` runs
   `trading/paper_loop.py --market crypto` → `live_paper_runner.main("crypto")`.
   There are **zero** `create_order`/`place_order` calls anywhere in `trading/`
   or `execution/`; fills are simulated (`_fill_price`). Binance/CCXT is used for
   **data fetch only**. The **$25/mo BTC DCA is exchange-side** (Binance app
   recurring buy) — not in this codebase, unreachable by a Python constant flip.
   `india`/`us` are not run by this container (and are halted).
3. **Simulated $200 book.** Entries update `paper_portfolio.json` /
   `paper_trades.db`. **Zero real capital at risk.**

## The change

- **A. Enable paper crypto entries:** `ENTRIES_DISABLED = False` in the 4 files;
  rebuild **only** `aaats-paper-crypto` (`--no-deps`). Siblings, india/us, and any
  live/DCA path untouched.
- **B. Entry tripwire snoozed for the window:** `scripts/box/aaats-entry-tripwire.sh`
  gains a window-guard — while `/srv/aaats/state/paper_entry_window_deadline`
  exists and is in the future, it suppresses (paper entries are expected, not an
  incident). Fail-safe: absent/malformed file → normal alerting.
- **C. Mandatory auto-revert:** `scripts/box/aaats-paper-window-revert.sh`
  (cron `*/15`, since `atd` is inactive) restores the `True` flags + rebuilds at
  the deadline, advances the tripwire watermark, removes the deadline file
  (re-arming the tripwire), removes its own cron, and Telegrams "window closed."
  **Fallback:** if the rebuild/verify fails, it sets the operator halt
  (`crypto:true`, no rebuild needed) as an immediate flat-gate and loudly alerts.

## Window

**7 days from deploy** (deadline epoch written to
`/srv/aaats/state/paper_entry_window_deadline`; ~2026-07-04). The system returns
to flat/entries-disabled **automatically** even if the operator forgets.

## Revert plan

Auto-revert handles the box. Manual revert (if the job ever fails) is in
`.rollback/2026-06-27_paper_entry_resume/MANIFEST.txt`. **The repo holds
`ENTRIES_DISABLED = False` only during this window** — restore the repo flags to
`True` after the window closes (the box auto-reverts independently; a box cron
cannot push code).

## Observe

Existing machinery only — weekly report (`runtime/REPORTS`), `paper_trades.db`,
and the dashboard (`dashboard/aaats_dashboard.html`, reads origin/main). Report
net paper PnL vs the no-trade baseline at window end.
