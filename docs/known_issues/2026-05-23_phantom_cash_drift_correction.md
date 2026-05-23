# Phantom cash drift correction: $184.85 → $193.37

**Discovered:** 2026-05-23 (post-incident analysis after operator question "is the bot working on profit?")
**Status:** FIXED (forensic adjustment, paper-only)
**Severity:** Low (paper accounting, no real money)

## What was wrong

After the 2026-05-23T13:29-15:07 phantom-position crash loop, `paper_portfolio.json["crypto"]["capital"]` showed $184.85 — but `paper_trades.db` only had a single $6.63 BUY row (TON/USDT, 15:07:46Z post-hotfix).

Expected cash: $200.00 (seed) − $6.63 (TON entry) = **$193.37**.
Actual cash: **$184.85** — drift of **−$8.52** with no matching ledger row.

The bot's Grafana Portfolio Capital tile showed $191.48 ($184.85 cash + $6.63 deployed) instead of the expected $200, despite the open TON position being unrealized-flat. C.7 profitability gate (final equity ≥ starting equity) would have been evaluated against this drifted baseline.

## Where it came from

During the crash loop (12:46 → 15:07), the C3 BUY emission path in `trading/altcoin_reversion.py` had this ordering:

```python
capital -= trade_usd           # cash deducted in memory
portfolio["capital"] = capital
state[sym] = {...}             # strategy state mutated
changed = True
_record(...)                   # DB write — silently caught failure
# end of cycle:
if changed: _save_state(state) # state persisted regardless
```

When `_record()` raised (datatype mismatch on the broken init_db schema — see `docs/known_issues/2026-05-23_pager_5plus_restart_not_firing.md` and the c71291e fix commit message), the silent catch left:
- cash deducted ✓
- state JSON updated ✓
- ledger row missing ✗

On each container crash + restart during the crash loop, the runner re-loaded the partial state (with the $8.52 stale deduction in capital) and the cycle repeated.

The orphan-position fix in c71291e (ledger-first ordering, raises on failure, caller skips state mutation on raise) prevents this in the future, but it cannot undo cash deductions that have no matching ledger row.

## Correction applied (2026-05-23 ~18:25Z)

Surgically wrote `paper_portfolio.json["crypto"]["capital"] = 193.37` via a one-shot `docker exec ... python` mutation while the runner was between cycles. Atomic `.tmp` + rename. Verified:
- File on disk: `capital: 193.37`
- aaats-metrics exporter scrape: `aaats_portfolio_capital{crypto}=200.00` (cash 193.37 + deployed 6.63)
- Grafana Portfolio Capital tile now reads **$200**

The soak counter, divergence-watcher, anomaly window, and all other state untouched. The TON open position untouched. Only the crypto-cash scalar was adjusted.

## Why this is defensible (paper-only)

1. The drift had no ledger row — no real trade explained it.
2. The doctrine amendment (`docs/decisions/2026-05-23_doctrine_amendment_200_floor.md`) explicitly seeds the soak at $200; the drift violated that invariant.
3. C.7's "final equity ≥ starting equity" gate is meaningless if the starting equity has been corrupted by infrastructure failure, not trading.
4. No real money was ever at risk — this is paper.

## What this is NOT

- Not a precedent for adjusting paper P&L going forward. The orphan-position fix means future cash deductions will always have matching ledger rows. If a future drift appears, that's a NEW bug to investigate, not a routine correction.
- Not a backdating of trades. The TON BUY row is preserved verbatim at 15:07:46Z with shares=3.72, price=$1.78, value=$6.63.
- Not a reset. The d5_day1_marker (2026-05-23T12:46:32Z), the anomaly window (13:29:44Z → 15:07:46Z), the watcher arming, and the soak counter are all intact.

## Cross-references

- `docs/decisions/2026-05-23_doctrine_amendment_200_floor.md` — defines the $200 seed.
- Commit c71291e — phantom-position root-cause fix.
- Commit 4219651 — session-11 hotfix MANIFEST (which archived broken paper_trades.db + altcoin_reversion_state.json but did NOT correct the cash drift, since the drift wasn't visible until operator-question follow-up).
- `tests/test_orphan_position_prevention.py` — regression pin for the underlying bug.
