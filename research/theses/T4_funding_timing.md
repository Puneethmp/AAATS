# Pre-Registration — T4 Funding-Rate Timing (T4a contrarian + T4b continuation)

> **STATUS: DRAFT — NOT YET REGISTERED.** Anti-snooping rule (binding): this file
> must be committed to origin/main BEFORE any signal or PnL computation. The commit
> SHA is the registration timestamp. No backtest may run until then. One harness run
> per thesis, seed=7. A FAIL is terminal — no re-tuning, no "v2" of the same sign.

## 0. Why two theses, not one

Funding-rate timing has two opposite, individually-plausible sign readings of the
*same* signal. Choosing the sign after seeing performance would be post-hoc
optimization. Per the operator multiple-comparison rule, both are registered as
**separate theses** and corrected together:

- **T4a — contrarian:** extreme funding marks crowded positioning that mean-reverts.
- **T4b — continuation:** extreme funding marks persistent directional conviction.

**Multiple-comparison control:** T4a + T4b are a co-registered family of 2 →
Bonferroni, null threshold **p97.5** (family-wise α = 5%), identical to the T1+T2
treatment. ALL other parameters are frozen to a single value (this is two sign
hypotheses, NOT a parameter sweep).

**Distinct from the closed boundary and from T1.** This is NOT carry: T1 tested
funding *dispersion to collect funding income* (declared economically void at
8.68 bps < 10 bps taker). T4 monetizes the **price move** of crowded names, not
the funding cashflow — funding is the *signal*, price is the *PnL*. It is also not
own-price OHLCV directional (the falsified C1/C2/C3/C6/TSMOM boundary): the trigger
is a positioning-flow variable absent from price.

## 0.5 Parameter provenance (a priori confirmation — binding)

All frozen parameters were chosen **a priori**, before any T4 computation. Explicitly,
for the lookback and every other §3 value:
- **No PnL was examined.** No T4 backtest of any kind has been run.
- **No OOS results were viewed.** No fold output, no Sharpe, no equity curve.
- **No comparison against alternative lookbacks** (or any other parameter setting)
  occurred. Exactly one value per parameter was reasoned out and frozen.

The only non-performance input to the 3-day lookback was *structural*: T1's registered
**carry** signal used a 7-day funding window, so a deliberately shorter window was set
to make T4 a *timing* read rather than carry. That is a design fact about another
thesis's frozen parameter — not data, PnL, or OOS performance. No funding-value or
return distribution was inspected to pick it.

## 1. Economic mechanism

Perp funding is the price of leverage demand. When a name's funding is at a
cross-sectional extreme, one side of its book is crowded and paying to stay on.
- **T4a (contrarian):** crowded longs (high funding) are vulnerable to a squeeze;
  crowded shorts (negative funding) to a short-cover rally. Short the most-positive,
  long the most-negative funding → profit if crowding reverts in price.
- **T4b (continuation):** sustained funding extremes mark conviction/trend; the
  crowd is right for longer than it is wrong. Long the most-positive, short the
  most-negative funding → profit if the trend persists.
Dollar-neutral L/S nets market beta out either way; the bet is purely on the
sign of the crowding→price relationship.

## 2. Data (free, on disk — no collection, no purchase)
- **Funding** (signal): `*_funding_u30.parquet`, 8h prints, 36 mo, 171 syms — on disk.
- **Price** (PnL): `*_1h_perp_u30.parquet`, 36 mo, 171 syms — on disk.
- **Universe:** `u30_universe_daily.parquet` (point-in-time membership) — on disk.
- **Paid data required:** NONE. No OI / liquidation / depth used.
- **Corrupt-row cleaning rule (FROZEN, part of the registered spec):** at load, any
  row whose timestamp has **year > 2100** is treated as corrupt and excluded; the panel
  is then clipped to the registered window [2023-05-28, 2026-05-27]. (Motivated by one
  U30 parquet carrying a year-4761 row.) This rule is frozen before the run and is
  included in the params_hash. No other data filtering is applied.

## 3. FROZEN PARAMETERS (one value each; one-line economic justification each)

| Parameter | Frozen value | Economic justification (one line) |
|---|---|---|
| **Universe** | point-in-time U30 (top-30 by trailing 30d median quote volume, onboardDate ≤ t−90d, no survivorship filter) | Broadest free point-in-time cross-section with depth ≫ our size; reuses the validated loader; 30 names → clean quintiles. |
| **Signal** | trailing **mean funding rate** per symbol | The level of leverage-demand pressure, smoothed across settlements, is the crowding measure — not its change or carry. |
| **Lookback** | **3 days** (= 9 × 8h settlements) | Long enough to smooth single-print 8h noise, short enough to be a *timing* read of *current* crowding (vs T1's 7d carry window). |
| **Threshold** | cross-sectional **quintiles**: extreme top 6 / bottom 6 of ranked funding | Rank-based extremity is self-calibrating across regimes and parameter-free (no tunable bps cutoff); 6/side matches T1/T2 at U30=30. |
| **Sign — T4a** | **SHORT** top-funding quintile, **LONG** bottom-funding quintile | Crowded side reverts: over-longed names fall, over-shorted names rise. |
| **Sign — T4b** | **LONG** top-funding quintile, **SHORT** bottom-funding quintile | Funding extreme = persistent conviction; follow the leveraged trend. |
| **Holding period** | **3-day** rebalance, full re-rank at 00:00 UTC, hold = lookback | Crowding is measured over 3 days, so it is expected to resolve over ~3 days; aligning hold to lookback is the principled (not cost-fitted) choice and keeps turnover honest under the fill model. |
| **Hysteresis / stops** | **none** | The 3-day re-rank IS the exit; no extra tunable bands or stop parameters. |
| **Portfolio** | $100 book, equal-dollar legs, **dollar-neutral** at construction | Removes the market-direction bet; per-trade return = leg pnl_net / leg notional. |
| **Fees** | taker **5 bps/side** on \|Δnotional\| turnover | Binance USDT-M VIP-0 taker; no maker assumption (conservative). |
| **Fill model** | `half_spread_bps=5.0`, `impact_coef_bps=10.0` (approved 2026-06-09) | Spread is the binding friction at $100; impact ≈ 0 but scales correctly. Removes close-mark/zero-friction false positives. |
| **Window** | 2023-05-28 → 2026-05-27 (36 mo) | Identical to Track F / T1 / T2 — comparability and a fixed pre-committed span. |
| **Corrupt-row rule** | exclude rows with year > 2100, then clip to window | Deterministic, frozen data-cleaning (one parquet has a year-4761 row); in the params_hash. |
| **Walk-forward** | 4mo train / 2mo OOS / 2mo step, anchored, non-overlapping, ≥15 folds (`make_folds`) | Frozen Track-F geometry; the project's validated OOS protocol. |

## 4. Acceptance gate (5-part, frozen — `xsect_walkforward.evaluate`)
ALL FIVE required; 4/5 = FAIL; no partial credit, no re-runs.
1. OOS net > 0 in ≥ 60% of folds
2. median per-fold OOS Sharpe ≥ 0.50 (per-trade, √60)
3. pooled-OOS daily Sharpe ≥ 1.0 (√365)
4. worst single-fold maxDD ≤ 20%
5. **null control:** pooled-OOS Sharpe > **97.5th** percentile (Bonferroni, T4a+T4b)
   of the registered null, 1000 draws, seed=7

- **Null model (frozen):** random-quintile selection — same rebalance dates, same
  6-per-side counts, same 3-day turnover mechanics, names drawn uniformly from the
  day's eligible U30 (`null_engines.null_distribution`). Preserves the identical fee
  + slippage load so the null isolates selection skill.
- **No economics pre-check:** T4 monetizes price, not funding income, so the T1-style
  funding-income void check is N/A. The harness runs directly once registered.

## 5. Pass / kill criteria
- **PASS (either thesis):** all 5 met → STOP, report verdict + null p-value +
  params-hash; recommend re-privatize repo + a realistic-fill forward soak. No live
  capital. A PASS on one sign does NOT license testing variants of it.
- **KILL (default):** one registered FAIL → archive that thesis permanently. Do NOT
  re-tune, do NOT flip to the other sign as a "fix" (the other sign is already its own
  registered thesis). A full T4a+T4b FAIL extends the falsification boundary to
  funding-timing flow signals — a valid, high-information outcome.

## 6. Frozen specification hashes (params_hash)
Computed by SHA-256 over the canonical sorted frozen-parameter object (§3 + §4),
first 12 hex. Any change to any frozen value changes the hash and voids registration.

- **T4a (contrarian)** params_hash: **`e40a8109a8c1`**
- **T4b (continuation)** params_hash: **`09a704a7a7eb`**

(The two hashes differ only by the `sign_convention` field — proof the sole
registered difference between the theses is the sign.)

## 7. Run record (filled AFTER registration + run — empty now)
- Registration commit SHA: `<pending — this file's commit>`
- T4a command: `.venv-nt/Scripts/python tools/nautilus/run_t4_funding_timing.py --thesis a`
- T4b command: `.venv-nt/Scripts/python tools/nautilus/run_t4_funding_timing.py --thesis b`
- Verdict JSONs: `data/graduation/T4a_funding_timing_<date>.json`, `…T4b…`
- Ledger lines appended: `<pending>`

---
*Drafted 2026-06-09. NOT registered until committed. No PnL has been computed.*
