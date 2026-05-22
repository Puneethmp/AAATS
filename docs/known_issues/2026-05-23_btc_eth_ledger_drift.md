# BTC/ETH ledger drift — root-cause triage

**Status:** ROOT CAUSE IDENTIFIED, behavior change deferred to unified-ledger sprint per autonomy contract.
**Authored:** 2026-05-22 (session 4).
**Trigger:** Session-3 deploy of `halt_on_critical=True` (commit `d1b7feb`) surfaced this drift as a reconciler-induced HALT-per-cycle restart loop on aaats-paper-crypto. Band-aid: reverted to `halt_on_critical=False` (session 3, operator-approved).
**Cross-refs:**
- [`scripts/reconcile_intracycle.py`](../../scripts/reconcile_intracycle.py) — the reconciler in question.
- [`trading/stat_arb.py`](../../trading/stat_arb.py) — the strategy producing the drift.
- [`docs/decisions/2026-05-22_live_flip_rebuild_plan.md`](../decisions/2026-05-22_live_flip_rebuild_plan.md) §"Status log" 2026-05-22 (session 3) `[1].b` — band-aid record.
- The unified-ledger sprint (separate doc, see `USE_UNIFIED_LEDGER` flag at `foundation.state_bridge`).

## Symptom

After session 3 deployed `halt_on_critical=True`, the reconciler HALTed every cycle on:

```
HALT crypto:BTC/USDT | expected=0.00000000 actual=0.00009052 drift=10000% |
    symbol_present_in_only_one_source
HALT crypto:ETH/USDT | expected=0.00000000 actual=-0.00330196 drift=10000% |
    symbol_present_in_only_one_source
```

Notional: BTC=$6.94, ETH=$7.54 (at last_price). Both exceed the $0.25 dust filter
in `scripts/reconcile_intracycle.py:130`, so the reconciler legitimately flags
them as catastrophic. The HALT cascade triggered a container restart loop
(RestartCount 6→14 in 5 min per session-3 status log).

## Root cause

Two independent bugs converging:

### Bug A — schema mismatch between writer and reader

The reconciler's **Source A** (canonical-positions reader,
`_load_strategy_state_positions` at
[`scripts/reconcile_intracycle.py:196-251`](../../scripts/reconcile_intracycle.py#L196-L251))
expects each strategy state file to map `symbol -> {entry_price, size_usd,
...}`. Skips silently if `entry_price` or `size_usd` is missing.

**C3 conforms:**
```json
// data/altcoin_reversion_state.json
{
  "ADA/USDT": {
    "entry_price": 0.2488,
    "entry_ts": "2026-05-20T23:09:39.545857+00:00",
    "size_usd": 14.58,
    ...
  }
}
```

**C1 DOES NOT conform:** stat-arb is a pair strategy, so its key is a pair
identifier and the per-leg fields are suffixed `_a`/`_b`:

```json
// data/stat_arb_state.json
{
  "BTC/USDT_ETH/USDT": {
    "side": "LONG_A",
    "shares_a": 9.051802910958044e-05,
    "shares_b": 0.0032771683933004022,
    "entry_price_a": 76667.57,
    "entry_price_b": 2117.62,
    ...
  }
}
```

When the reconciler's Source-A loader iterates `stat_arb_state.json`:
- `symbol_key = "BTC/USDT_ETH/USDT"` (not a real symbol).
- `pos.get("entry_price")` → `None` (the field is `entry_price_a`/`entry_price_b`).
- The `if not entry_price ... continue` guard skips this entry **silently**.

Net effect: Source A sees ZERO position for both BTC/USDT and ETH/USDT, even
though C1 is holding an open `LONG_A` pair.

### Bug B — Source B counts C1's legs as net positions

Source B (`_compute_positions_from_db` at
[`scripts/reconcile_intracycle.py:306-345`](../../scripts/reconcile_intracycle.py#L306-L345))
sums `BUY shares - SELL shares` per `(market, symbol)`, **excluding only
`C5b_funding_arb`**:

```python
"WHERE strategy != 'C5b_funding_arb' "    # exclude delta-neutral arb
```

C1_stat_arb is also delta-neutral arb (long one leg, short the other), but
its leg trades are NOT excluded from Source B. Verified on box
2026-05-22T17:50Z:

| Symbol | Source A (state file) | Source B (DB net) | Reconciler verdict |
|---|---|---|---|
| BTC/USDT | 0.00000000 (silently skipped) | +0.00009052 (C1 BUY leg, 1 trade) | `symbol_present_in_only_one_source` HALT |
| ETH/USDT | 0.00000000 (silently skipped) | −0.00330196 (C1 SELL leg, no matching BUY; C3 had a near-matching BUY+SELL pair) | `symbol_present_in_only_one_source` HALT |

The ETH/USDT case is even worse than a missed open leg: net is **negative**
because Source B has only a SELL trade for C1 (the short leg of `LONG_A`) and
no opening BUY for C1. A negative `expected==0 != actual` is the catastrophic
branch on `scripts/reconcile_intracycle.py:416`.

The current `paper_trades.db` schema does not have a "leg of pair" concept;
C1's short legs are recorded as plain SELLs. The reconciler has no way to
recognize them as legs vs. real position closes — except by excluding the
strategy entirely (the C5b pattern).

## Why this surfaced now (and not 2026-05-12)

- C1 stat_arb was **silent for most of the rebuild window** because of the
  poisoned correlation cache (`stat_arb_health.json` showed `pair_healthy=False`
  through 2026-05-21). Per session-2 status log, the cache was invalidated
  on 2026-05-22T03:54Z and C1 opened its first BTC/ETH pair on
  2026-05-22T15:41:18Z (entry_time in `stat_arb_state.json`).
- The same session deployed `halt_on_critical=True` in
  `trading/live_paper_runner.py:1881`.
- The combination — first ever C1 entry on the same day the reconciler became
  authoritative — caused the immediate restart loop.

## The one-line fix path (deferred to unified-ledger sprint)

Three options ranked by leverage:

### Option A (band-aid, smallest) — exclude C1 from Source B

`scripts/reconcile_intracycle.py:323`:

```diff
- "WHERE strategy != 'C5b_funding_arb' "    # exclude delta-neutral arb
+ "WHERE strategy NOT IN ('C5b_funding_arb', 'C1_stat_arb') "    # exclude delta-neutral arb (pair + funding)
```

Symmetric with the C5b exclusion. **One-line change.** Restores the ability
to re-enable `halt_on_critical=True` without restart-loop.

**Downside:** the reconciler loses ALL drift detection for C1. If C1 leaks
a position (e.g., crash mid-exit leaves one leg unwound), the reconciler will
never catch it. This is the same blind spot C5b has today.

### Option B (proper, moderate) — teach the reconciler C1's pair schema

`scripts/reconcile_intracycle.py:227` — extend
`_load_strategy_state_positions` to recognize pair-keyed entries:

```python
# NEW branch: pair-keyed entries (e.g. C1 stat_arb "BTC/USDT_ETH/USDT")
if "shares_a" in pos and "shares_b" in pos:
    long_sym, _, short_sym = symbol.partition("_")
    side = pos.get("side", "")
    # side == LONG_A: long leg A, short leg B
    # side == LONG_B: short leg A, long leg B
    sign_a, sign_b = (+1, -1) if side == "LONG_A" else (-1, +1)
    shares_a = float(pos.get("shares_a", 0.0) or 0.0) * sign_a
    shares_b = float(pos.get("shares_b", 0.0) or 0.0) * sign_b
    market = pos.get("market", "crypto")
    out.setdefault(market, {})
    # Accumulate signed shares per leg-symbol.
    out[market].setdefault(long_sym, {"shares": 0.0, "size_usd": 0.0, "entry_price": 0.0})
    out[market][long_sym]["shares"] += shares_a
    out[market].setdefault(short_sym, {"shares": 0.0, "size_usd": 0.0, "entry_price": 0.0})
    out[market][short_sym]["shares"] += shares_b
    continue
```

**Downside:** the reconciler's existing data structure tracks
`shares: float` as a non-negative magnitude. Carrying signed values breaks
the dust-filter math (`abs(residual)`) and the catastrophic-branch logic
(`expected == 0.0 != actual == 0.0` is ambiguous when negative). The full
refactor is several touchpoints, not one line.

### Option C (unified ledger, large) — single canonical positions table

The unified-ledger sprint introduces one positions table that all strategies
write to with a consistent schema. Source A becomes one SQL query. Source B
becomes the immutable paper_trades audit log. Reconciler compares the two
without per-strategy special-casing. This is the only path that closes the
class of bugs (Bug A) rather than playing whack-a-mole.

The relevant flag is already wired:
`foundation.state_bridge.is_unified_ledger_enabled()` at
`trading/stat_arb.py:70`. When the flag is on AND all strategy writers route
through `_state_bridge.save_state`, the reconciler can be rewritten to read
the unified table instead of glob-walking `*_state.json`.

## Recommendation

**Path for next session's box deploy (i.e., to re-enable `halt_on_critical=True`):**
ship **Option A** as a single-line strategy-exclude. It is reversible, low-risk,
and unblocks D.2 watchdog + A.1 state-isolation from depending on the
band-aid. Document the C1 drift blind-spot as a known limitation closed
later by Option C.

**Path for unified-ledger sprint:** ship **Option C**. Re-instate full C1
drift detection at that point. Option B is NOT recommended as a standalone
step — the partial signed-shares refactor is more code than Option C with
none of its benefits.

## Action needed

NONE this session per the autonomy contract (ledger writer changes are
doctrine-adjacent). Option A is a one-line patch that should land as the
first item of the next reconciler-touching session. Until then, the band-aid
`halt_on_critical=False` at `trading/live_paper_runner.py:1881` stays.

## Verification recipe (re-run after any change)

```bash
docker exec aaats-paper-crypto python /tmp/diag_btc_eth.py
```

(See `c:\tmp\diag_btc_eth.py` on the operator workstation for the diag
script; copies to the box via paramiko + `docker cp`.)

Expected after Option A: Source B drops the C1 legs, BTC/ETH residuals
become 0.00000000, reconciler PASSES, `halt_on_critical=True` is safe to
re-enable.

## Status log

- **2026-05-22 (session 4)** — Root cause identified. Two bugs: schema
  mismatch between C1's pair-keyed state file (`stat_arb_state.json`) and
  the reconciler's C3-shaped Source-A reader, AND missing C1 exclusion in
  Source B's SQL filter (parity gap with C5b). Three fix paths documented;
  Option A recommended as next-session one-line patch. NO behavior change
  this session per autonomy contract.
