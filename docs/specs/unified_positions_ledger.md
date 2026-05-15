# Spec: Unified Positions Ledger

**Status:** draft — needs operator review before any implementation
**Author:** Claude (2026-05-15 session, post P0/P1 deploy)
**Driver:** TON/FET reconcile divergence (2026-05-15) traced to exit-sizing bug exposing N-source-of-truth problem; [2026-05-15_drift_diagnosis.md](../decisions/2026-05-15_drift_diagnosis.md) frames the architectural debt. (Originally referenced an operator-local memory file — mirrored into the repo on 2026-05-15.)

## Problem statement

The reconciler compares two derived views of the position book:

- **Source A** — aggregation of per-strategy state files (`data/*_state.json`); each strategy file owns its own positions.
- **Source B** — `SUM(BUY.shares) - SUM(SELL.shares)` from `paper_trades.db`, a side-effect of audit logging.

Both are derived; neither is canonical. Every new strategy adds an A-side
ledger that the reconciler must learn about. Every exit-sizing bug (see
TON/FET 2026-05-15: SELL shares computed as `size_usd / exit_price` instead of
the entry quantity) creates a persistent B-side residual that the dust filter
only partially masks. The result is a reconciler that ratchets toward
"always-tripping" as strategy count grows.

This spec proposes collapsing both into a single in-database `positions`
table that is the operational source of truth, with strategies reading and
mutating through a thin API.

## Proposed schema

A new table `positions` in `data/paper_trades.db` (same DB so all state lives in one place):

| column          | type    | null | notes                                                |
|-----------------|---------|------|------------------------------------------------------|
| symbol          | TEXT    | NO   | `BTC/USDT` etc; PRIMARY KEY together with `strategy` |
| strategy        | TEXT    | NO   | `C3_altcoin_reversion`, etc.                         |
| market          | TEXT    | NO   | `crypto` / `india` / `us`                            |
| entry_shares    | REAL    | NO   | exactly what was filled (not `size_usd/entry_price`) |
| entry_price     | REAL    | NO   | for PnL / exit comparison                            |
| size_usd        | REAL    | NO   | notional at entry                                    |
| entry_ts        | TEXT    | NO   | ISO8601 UTC                                          |
| entry_correlation_id | TEXT | YES | links to the BUY row in `paper_trades`              |
| metadata_json   | TEXT    | YES  | strategy-specific blob (entry_z, entry_pct_b, vol…) |

Composite primary key `(strategy, symbol)` lets two strategies hold the same
symbol independently without collision.

Rows are inserted on BUY fill, updated only by the owning strategy, and
deleted on SELL fill. There is no "partial close" — the spec assumes
all-or-nothing exits (current behavior). Partial closes can extend with a
separate `realized` column later.

## API surface

```python
# foundation/positions.py
def open_position(strategy, symbol, market, entry_shares, entry_price,
                  size_usd, entry_ts, correlation_id=None, metadata=None) -> None: ...
def close_position(strategy, symbol) -> dict | None: ...
def get_position(strategy, symbol) -> dict | None: ...
def list_positions(strategy: str | None = None,
                   market: str | None = None) -> list[dict]: ...
```

Strategies stop reading/writing `*_state.json`. They call `open_position`
inside their BUY branch and `close_position` inside their SELL branch.
`metadata_json` carries the strategy-private exit-criteria state
(`entry_z`, `max_z`, `entry_pct_b`, `symbol_vol`) so nothing in the
strategy file is lost.

## Migration plan

One-time script `scripts/migrate_positions_to_db.py`:

1. Read each `data/*_state.json` (excluding `*cooldown*.json` and `halt_state.json`).
2. For every `(symbol, pos)` pair, compute `entry_shares`. **Preferred:** look up the matching BUY row in `paper_trades.db` by `(strategy, symbol, ts ≈ entry_ts)` and copy the actual `shares` value — this fixes the exit-sizing bug retroactively. **Fallback:** if no BUY row found within ±5min, use `size_usd / entry_price` and log a warning.
3. Insert into `positions` table.
4. Rename state files to `*_state.json.migrated_2026-05-15` (do not delete — keep one rollback cycle).
5. Print before/after counts and any fallback warnings.

Strategy code changes (one PR per strategy, all behind a `USE_UNIFIED_LEDGER` env flag for staged rollout):

- `trading/altcoin_reversion.py`: replace `_load_state()` / `_save_state()` with `foundation.positions` calls.
- `trading/bollinger_range.py`: same.
- `trading/momentum.py`, `trading/stat_arb.py`: same.
- Strategy unit tests need an in-memory positions table fixture.

## Reconciler change

`scripts/reconcile_intracycle.py` becomes a two-source diff:

- **Source A** = `SELECT … FROM positions` (canonical ledger; one row per open position).
- **Source B** = `SUM(BUY) - SUM(SELL)` from `paper_trades` (unchanged; serves as broker analogue).

No more "union over `*_state.json` files." No more entry-vs-actual share
ambiguity, because `positions.entry_shares` is the real fill quantity and
matches the BUY row by construction. The dust filter stays for genuine
ledger-rounding artifacts (1e-8 share residuals from float arithmetic) but
the systematic exit-sizing drift goes to zero.

When live trading begins, Source B is replaced with a broker `get_account`
call. The interface — "canonical ledger vs external view" — is preserved.

## What breaks if strategy #13 lands before this is done

- Reconciler has to learn a new `*_state.json` shape — every new strategy is a reconciler PR.
- Any divergence in the new strategy's exit-sizing logic adds another persistent residual symbol to the drift log; dust filter has to be re-tuned per strategy.
- Halt-state semantics get murkier as more sources accumulate; "true source of truth" becomes "majority vote across N files."
- More urgently: PRs to fix exit-sizing bugs become per-strategy whack-a-mole instead of a one-line fix in `close_position`.

Conclusion: build the unified ledger before strategy #13. Block any new strategy PRs that introduce a fresh state file.

## Open questions for operator review

1. **DB location:** keep `positions` inside `paper_trades.db`, or split into a separate `positions.db`? (Recommendation: same DB — atomic transactions across BUY-row + positions-row matter.)
2. **Cash ledger:** out of scope of this spec, but the same N-source problem exists for `paper_portfolio.json` vs DB-derived cash. Tackle in a follow-up?
3. **Metadata schema:** keep `metadata_json` as opaque text per strategy, or define a typed sub-schema (strategy = "altcoin_reversion" → `{entry_z, max_z, …}`)? The opaque path ships faster; the typed path is queryable.
4. **Migration rollback:** the `.migrated_2026-05-15` rename is recoverable, but a strategy mid-cycle could double-write to both files+DB if the flag flips during a cycle. Do we want a "drain cycle" gate between flag-off and flag-on?

## What this spec is NOT

- Not a fix for the live TON/FET drift — that is a separate strategy-code patch (see `docs/known_issues/` once filed).
- Not a unified cash/PnL ledger — positions only.
- Not a rewrite of the kill switch or reconciler thresholds — those policies remain unchanged.
