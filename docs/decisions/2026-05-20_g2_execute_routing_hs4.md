# 2026-05-20 — HS4 invoked: G2 "route C3/C6 through execute()" architectural mismatch

**Session status:** halted at Step 1 (pre-flight audit). No code modified, no deploys, no commits.
**Trigger:** Hard-stop HS4 — "execute()'s state management irreconcilably conflicts with strategy state files."
**Reporter:** Phase 0 completion attempt 2026-05-20T autonomous session.

---

## Audit findings

`trading/live_paper_runner.py:861` (`execute()`) and the two C3/C6 strategy
runners (`trading/altcoin_reversion.py`, `trading/bollinger_range.py`) are two
**independent execution paradigms** that both terminate at `paper_trades.db` and
both mutate `portfolio["crypto"]["capital"]`. They do not currently overlap on
any single trade, but they cannot be merged without resolving five concrete
conflicts.

### Paradigm A — runner-routed (current execute() callers)

`execute()` owns:
1. **Sizing** — Kelly-weighted ATR position size via `_get_sizer(market, capital).calculate_position_size(...)` (`live_paper_runner.py:911`).
2. **DB recording** — `record_trade(...)` with `strategy=f"{market}_directional"` and notes `{"confidence", "ml_scale", "atr_entry", "risk_pct"}` (`live_paper_runner.py:935-944`).
3. **Position ledger** — `mkt_pos[symbol] = {"shares", "entry_price", "entry_time", "regime", "sector", "atr_entry", "risk_pct"}` (`live_paper_runner.py:945-953`).
4. **Capital math** — `mkt_port["capital"] -= value` on BUY, `+= value` on SELL (`live_paper_runner.py:955, 997`).
5. **HOLD branch stop-loss** — when called with non-BUY/SELL signal and symbol is in `mkt_pos`, forces SELL on `pnl_pct < -2.0*atr_entry/entry_price` (`live_paper_runner.py:1022-1033`).
6. **Risk engine gate** — `engine.check_new_order(...)` per-order plus the HALT_ALL/HALT_MARKET portfolio gate at the top (`live_paper_runner.py:889-894, 919-924`).
7. **Sizer heat** — `sizer.add_position_heat(risk_pct)` / `remove_position_heat` (`live_paper_runner.py:954, 990`).

Callers (`live_paper_runner.py:1030, 1434, 1528`) pass `(market, symbol, signal, regime, confidence, last_price, features, positions, portfolio, sector, ml_size_scale, strategy)`. None inspect the (None) return.

### Paradigm B — strategy-routed (C3, C6, also C2 momentum_breakout and stat_arb)

C3 (`altcoin_reversion.py:398`) and C6 (`bollinger_range.py:213`) each own
their own copy of items 1–5 above and bypass items 6–7 entirely:

| Item | C3 location | C6 location |
| --- | --- | --- |
| Sizing | `_compute_trade_size()` — vol-adjusted, `POSITION_USD * (VOL_REF / symbol_vol)` clamped `[0.5x, 1.5x]` (`altcoin_reversion.py:212-247`) | `trade_usd = capital * CAPITAL_PCT` (`bollinger_range.py:356`) |
| DB record | `_record(...)` writes `strategy="C3_altcoin_reversion"`, custom notes incl. `z_score`, `exit_reason` (`altcoin_reversion.py:353-394`) | `_record(...)` writes `strategy="C6_bollinger_range"`, notes incl. `pct_b`, `rsi`, `exit_reason` (`bollinger_range.py:175-209`) |
| Ledger | `data/altcoin_reversion_state.json` — `{entry_price, entry_ts, size_usd, entry_z, max_z, symbol_vol}` per symbol | `data/bollinger_range_state.json` — `{entry_price, entry_ts, size_usd, entry_pct_b, entry_rsi}` per symbol |
| Capital math | `capital -= trade_usd; portfolio["capital"] = capital` BUY (`:559-560`); `capital += size + pnl` SELL (`:489-490`) | Same pattern (`:363-364, 306-307`) |
| Stop logic | `_should_exit()` based on z-score (overshoot, trailing, hard stop, time stop) (`:318-349`) | Inline: `pct_b >= 0.50`, `pnl_pct >= 1.5%`, `pnl_pct <= -1.0%`, `age >= 12h`, `regime_flip` (`:292-303`) |

C3/C6 also receive only the **crypto sub-portfolio** (`portfolio["crypto"]`) and
have no handle on the full `positions`/`portfolio` dicts that `execute()`
requires.

---

## Why routing through execute() is HS4

To literally route C3/C6 through `execute()` (Option A in the plan), at least
five conflicts must be resolved:

| # | Conflict | Minimum bridging cost |
| --- | --- | --- |
| 1 | Sizing — `execute()` runs Kelly+ATR sizer; C3/C6 own custom sizing | NEW `precomputed_shares` kwarg + branch that skips `sizer.calculate_position_size(...)` |
| 2 | DB recording duplication — both paths call `record_trade` for the same trade | NEW `skip_record_trade` kwarg OR remove C3/C6 `_record()` (breaks strategy-specific notes: `z_score`, `exit_reason`, `pct_b`, `rsi`) |
| 3 | Capital double-debit — C3/C6 already mutate `portfolio["crypto"]["capital"]`; `execute()` would too | NEW `skip_portfolio_capital` kwarg OR remove C3/C6 capital lines (couples strategy capital math to runner) |
| 4 | Cross-strategy SELL/HOLD interference — once C6 BTC sits in `mkt_pos`, the runner's per-symbol signal loop (`run_crypto:1528`) on the next cycle calls `execute("BTC/USDT", signal=...)`. SELL would pop C6's position; HOLD with a missing `atr_entry` would force-SELL on a 4% trailing stop derived from `last_price*0.02*2.0` | NEW `strategy_owned` marker on `mkt_pos` entries + 2 new guard branches (SELL handler and HOLD fall-through) |
| 5 | Public-API of C3/C6 — both currently receive `portfolio["crypto"]` only. To call `execute()` they need full `positions` and `portfolio` dicts | Signature change to `run_altcoin_reversion_crypto(...)` and `run_bollinger_range_crypto(...)` + call-site updates in `run_crypto` |

J2 says: *"strictly additive (new optional kwargs with sensible defaults). NEVER
breaking changes. Breaking change required = HS4."*  Three new kwargs on
`execute()`, two new control-flow branches gated on a new `mkt_pos` marker, and
two strategy-runner signature extensions exceeds the spirit of "strictly
additive." Even on the most-charitable reading where each individual addition
is "additive," the aggregate is a refactor — and J2 explicitly carves out
exactly this scenario.

The OR clause of HS4 also applies: each strategy's state file holds
**strategy-specific decision inputs** (`max_z` for C3 trailing exit, `entry_pct_b`
for C6) that `mkt_pos` cannot store without becoming heterogeneous and that
`execute()` cannot consume without knowing per-strategy exit logic. Reconciling
these requires keeping BOTH ledgers in sync per trade (state file for strategy
logic, mkt_pos for system-level position awareness), which is precisely the
"dual-ledger inconsistency risk" the prompt rejected in Option B.

The 1696-line file (`live_paper_runner.py`) also shows the plan's reference
**line 1696 is not where halt_on_critical lives** — the actual flag is at
`live_paper_runner.py:1731` inside the intra-cycle reconciler block. Not a
showstopper, just noted for the next attempt.

---

## Proposed redesign options (user picks)

### Option B′ — Shared kill-switch gate helper (RECOMMENDED)

Extract the HALT_ALL/HALT_MARKET portion of `execute()` (lines 879–894) into a
small public helper:

```python
def apply_kill_switch_gate(
    market: str, symbol: str, last_price: float,
    positions: dict, portfolio: dict,
) -> tuple[bool, str]:
    """Returns (allowed, reason). Centralizes the engine.update_portfolio/
    update_market HALT gate so self-managed strategies can honor it without
    routing their full BUY/SELL through execute()."""
    engine = _get_risk_engine(portfolio)
    total_equity  = _compute_current_equity(positions, portfolio, market, symbol, last_price)
    engine.update_portfolio(total_equity)
    market_equity = _compute_market_equity(positions, portfolio, market, symbol, last_price)
    decision = engine.update_market(market, market_equity)
    if decision.action in ("HALT_ALL", "HALT_MARKET"):
        return False, decision.reason
    return True, ""
```

Call from `execute()` (refactor — no behavior change) AND from C3/C6 at the
top of their BUY/SELL branches:

```python
allowed, reason = apply_kill_switch_gate("crypto", sym, current_price, positions_full, portfolio_full)
if not allowed:
    log.info("[c3] %s: SKIP — kill switch active (%s)", sym, reason)
    continue
```

C3/C6 still need access to full `positions`/`portfolio` (conflict 5) — that's
unavoidable for any kill-switch wiring — but they keep their sizing, recording,
state files, and capital math intact.

**Pros:** ~40 LOC across 3 files; no `mkt_pos` cross-contamination; G1 flip
becomes meaningful for C3/C6; rollback is per-file simple.

**Cons:** doesn't surface C3/C6 positions in `mkt_pos` (cross-strategy collision
between C2 and C6 on BTC/ETH remains; today C6 self-guards via its
`open_positions` check at `bollinger_range.py:338-343`, but the reverse is not
guarded — C2 BUYing BTC when C6 holds it is still possible).

### Option A′ — Full execute() routing with kwarg-extension + dual ledger

Pay all five conflict-bridging costs above. Stricter cross-strategy safety,
but ~100 LOC across 4 files plus a signature change to two strategy runners
plus a new `strategy_owned` field that the rest of the codebase must learn
about (reconciler at `scripts/reconcile_intracycle.py`, allocator at
`markets/crypto/allocator.py`, share-equality detector in
`execution/paper_trader.py`).

Recommended only if the user wants C3/C6 to also participate in `mkt_pos` for
cross-strategy collision detection — but a much simpler way to get that
specific property is to have the strategies write a parallel
`positions[market][symbol]` entry without going through `execute()` at all.

### Option C′ — Defer G2, ship G1 + OBS now

`halt_on_critical=True` at `live_paper_runner.py:1731` and the CYCLE_SUMMARY
observability commit are both independent of the G2 routing question:

- G1 covers the reconciliation-driven HALT (drift > 2% on any position
  triggers `foundation.kill_switch.halt()`). This already operates outside
  `execute()` and gates the entire main loop via the `break` at line 1738.
  Flipping `halt_on_critical=True` makes the reconciler ACTUALLY halt instead
  of warn — that property is true regardless of how C3/C6 route their trades.

- OBS is a single `_emit_cycle_summary()` call at the end of the cycle that
  reads strategy state files. Zero coupling to G2.

Risk: G2's kill switch (portfolio-level HALT_ALL/HALT_MARKET via
`risk_engine.update_market(...)`) would still NOT be enforced for C3/C6
entries until G2 ships in a follow-up. The reconciler HALT (G1) catches a
different failure mode (silent drift between ledger and broker), so the two
are complementary, not substitutes.

---

## Recommendation

**Option C′ in this session: ship G1 + OBS** (both independent and low-risk),
**bank G2 for a follow-up session** using Option B′ (shared kill-switch gate
helper). Two atomic commits today, one architectural-decision doc, one memory
update. G2 then lands cleanly when a follow-up plan is written against the
actual codebase shape rather than against the assumed shape.

If the user prefers Option A′ (full literal routing), it should be its own
multi-session sprint with explicit dual-ledger spec sign-off — the same way
C5b's halt happened pending the unified-ledger spec.

---

## What was NOT touched

- No code modified in this session.
- No deploys attempted.
- No commits created.
- No rollback baselines written (none needed — nothing changed).
- `data/share_equality_mismatches.json` left at `{}` (unchanged).
- All recent commits on `origin/main` remain the head:
  `ef5544c → f137cb3 → f402beb → 51fdb08 → 38a7db4`.

## Items banked for the next session

1. Decide between Option B′ and Option A′ for G2.
2. Ship G1 (halt_on_critical=True at `live_paper_runner.py:1731` — note: NOT 1696).
3. Ship OBS — CYCLE_SUMMARY at end of `main()` cycle loop (`live_paper_runner.py:1707-1759`).
4. Carry over Phase-1 backlog from the original plan (BTC/ETH pair selection, C6 correlation_guard cap, doctrine threshold reviews).
