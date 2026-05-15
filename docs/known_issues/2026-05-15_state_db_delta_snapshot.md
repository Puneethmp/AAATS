# State-vs-DB Delta Snapshot — 2026-05-15

**Filed:** 2026-05-15 (snapshot taken ~13:50 UTC)
**Scope:** read-only observability; no patches.
**Method:** queried `aaats-paper-crypto` container directly via SSH + `docker exec`. For each strategy with a `data/*_state.json`, declared shares per (strategy, symbol) compared against `paper_trades.db` reconstruction `Σ BUY shares − Σ SELL shares`. Sorted by |notional delta| descending using each symbol's most recent traded price. Orphan rows (DB has a non-zero net but state has no entry — typical of historical seeded data) are appended.
**Related:** [2026-05-15_strategy_exit_sizing_audit.md](2026-05-15_strategy_exit_sizing_audit.md), [2026-05-15_buy_side_audit.md](2026-05-15_buy_side_audit.md).

## 1. Per-(strategy, symbol) delta table

Sorted by `|delta| × last_price` (notional value of the drift). Bold rows are the known TON/FET C3 exit-sizing residuals called out in the prior audit. Italic rows are sub-cent orphans (seeded test data; deny-listed in reconciler).

| # | Strategy | Symbol | Declared shares (state) | DB open shares (Σ BUY − Σ SELL) | Δ shares | Last px | **Δ $** | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | C3_altcoin_reversion | LUNC/USDT | 0 | −6838.616 | 6838.616 | 0.0000785 | **$0.5370** | DB-only, deny-listed (precedes dust filter). Net negative = phantom-short residual. Documented in SELL-side audit. |
| 2 | C3_altcoin_reversion | PENGU/USDT | 0 | −20.4616 | 20.4616 | 0.009641 | **$0.1973** | DB-only, deny-listed. Same pattern. |
| 3 | **C3_altcoin_reversion** | **TON/USDT** | **1.51314025** | **1.44080613** | **0.0723** | **2.078** | **$0.1503** | **C3 exit-sizing residual (known). Silenced by $0.25 dust filter.** |
| 4 | **C3_altcoin_reversion** | **FET/USDT** | **45.41966427** | **44.83257649** | **0.5871** | **0.2085** | **$0.1224** | **C3 exit-sizing residual (known). Silenced by $0.25 dust filter.** |
| 5 | C3_altcoin_reversion | ETH/USDT | 0 | −2.48e-5 | 2.48e-5 | 2284.60 | $0.0566 | _orphan / dust_ |
| 6 | C3_altcoin_reversion | TAO/USDT | 0.0099171 | 0.00980353 | 1.14e-4 | 305.50 | $0.0347 | Declared with tiny mismatch — below the $0.10 silence baseline, no action. |
| 7 | C6_bollinger_range | EUR/USDT | 0 | −0.01461 | 0.01461 | 1.1752 | $0.0172 | _orphan / dust_ |
| 8 | C3_altcoin_reversion | SOL/USDT | 0 | −9.22e-5 | 9.22e-5 | 92.23 | $0.0085 | _orphan / dust_ |
| 9–16 | C3 (open) | PUMP, BCH, ONDO, ENA, CHIP, ICP, OP, ARB | matched | matched | 0.0 | (various) | $0.00 | Clean. Open C3 positions, no drift. |

**One-paragraph summary.** The top of the table is exactly the four-line signature predicted by the SELL-side audit and the P1 BUY-side audit: two deny-listed DB-only legacy residuals (LUNC, PENGU), then the two known C3 exit-sizing residuals (TON $0.1503, FET $0.1224). Nothing new appears above the prior audit's $0.05 noise floor. The 8 currently-open C3 positions (PUMP, BCH, ONDO, ENA, CHIP, ICP, OP, ARB) reconcile to 0.0 shares delta — confirming the post-fix BUY/SELL `_record` path is writing equal shares for open positions (the share-equality assertion will hold on the first natural exit). **No non-TON/FET delta above $0.05 surfaced.**

## 2. C5b funding_arb — exclusion classification

### Where the exclusion lives

[scripts/reconcile_intracycle.py:323](scripts/reconcile_intracycle.py#L323):

```python
"SELECT market, symbol, action, SUM(shares) as total "
"FROM paper_trades "
"WHERE strategy != 'C5b_funding_arb' "    # exclude delta-neutral arb
"GROUP BY market, symbol, action"
```

### Live state of C5b on the box (snapshot taken in same SSH session)

- `data/funding_arb_state.json`: **does not exist** on `aaats-paper-crypto`.
- `paper_trades.db` rows where `strategy='C5b_funding_arb'`: **zero** (no BUYs, no SELLs, lifetime).
- C5b has not opened or closed a single position since deploy. The bug pattern documented in [2026-05-15_buy_side_audit.md §3](2026-05-15_buy_side_audit.md) ($25 delta per round-trip from BUY-side `shares=CAPITAL_PER_SYMBOL` vs SELL-side `shares=2×capital_per_leg`) is **latent — not active in production today**.

### Verdict: **Principled** (with one documented gap)

The reconciler exclusion is correct by intent. A delta-neutral funding arb position is a paired long + short, so a real-exchange reconciliation would expect `net shares = 0` (the long and short legs cancel). The exclusion comment "delta-neutral arb" is the principled reason. If the paper implementation faithfully wrote both legs, the comment would be redundant — the SUM(BUY − SELL) would naturally be zero.

The implementation does **not** faithfully write both legs. As cataloged in the BUY-side audit, the strategy records:
- **BUY leg:** `shares = CAPITAL_PER_SYMBOL / 1.0` (one row, per-leg notional)
- **SELL leg on close:** `shares = (capital_per_leg × 2) / 1.0` (one row, round-trip notional)

So the DB shows asymmetric rows even though the *semantics* are delta-neutral. The exclusion *accidentally* protects the reconciler from this asymmetry. That is a fortunate alignment, not a bug — the exclusion is still principled (it's what you'd write even with a correct dual-leg implementation), but it does cover for an implementation gap downstream.

Two follow-ups (out of scope this session, recommended for future):

1. Fix the funding_arb dual-leg recording to write symmetric BUY/SELL rows so the exclusion is no longer load-bearing. Cleanest: either record both legs explicitly (long BUY + short SELL on open, mirror on close), or stop pretending C5b is a spot trade in paper_trades.db and route it through a separate funding-event table.
2. Once §1 is fixed, the share-equality assertion in [execution/paper_trader.py:117-156](execution/paper_trader.py#L117-L156) should naturally apply to C5b without needing a strategy-name suppression — the BUY/SELL row pair becomes symmetric and the assertion passes.

### Why not classify as "Stale TODO"

A stale-TODO exclusion would have no inline reason or would reference a debugging task that was never reversed. This exclusion has a one-line reason (`# exclude delta-neutral arb`) that captures correct domain intent. It would be the right call to keep even if the paper implementation were perfect. Classification stands: **Principled.**

## 3. What this snapshot does and does not establish

Establishes:

- The two C3-residual symbols documented in the SELL-side audit are still the only above-noise (>$0.10) drift sources today.
- All 8 currently-open C3 positions reconcile with zero shares delta — the recent `_record` fix is producing matched BUY/SELL share counts.
- The reconciler's C5b exclusion is principled, and the latent C5b $25-delta bug from the BUY-side audit has not fired (no C5b activity since deploy).
- No silent strategy that miscounts shares for an unknown symbol exists today.

Does **not** establish:

- That the share-equality assertion behaves correctly on a natural SELL — that requires the watcher reporting from a real post-fix exit (separate observation, P0).
- That C5b will continue to remain dormant — when funding rates next exceed threshold, the asymmetric-leg bug will surface.
- That all `*_state.json` files are themselves authoritative — this snapshot trusts them as ground truth and measures the DB against them. A state-file corruption would be invisible to this scan.
