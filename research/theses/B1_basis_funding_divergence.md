# Pre-Registration — B1 Basis–Funding Divergence (B1a contrarian + B1b continuation)

> **STATUS: FINALIZED PROPOSAL — NOT YET REGISTERED.** Anti-snooping rule (binding):
> this file must be committed to origin/main BEFORE any premium-index data is fetched
> for signal use, any signal is computed, or any PnL is run. The commit SHA is the
> registration timestamp. One harness run per thesis, seed=7. A FAIL is terminal —
> no re-tuning, no "v2" of the same mechanism.

## 0. Purpose — test INCREMENTAL information, not a funding re-test

T4 (funding timing) was falsified both signs. This thesis does NOT re-test funding
with a different proxy. The signal is constructed to **strip out the funding level
T4 already tested** and ask the orthogonal question: *does the premium index carry
predictive information that the settled funding rate does not?* A PASS = genuine
incremental basis information; a FAIL = the falsification boundary cleanly extends to
"basis carries nothing beyond funding."

Two opposite, individually-plausible sign readings → registered as **separate theses**,
Bonferroni **p97.5** (family of 2), identical treatment to T4a/T4b.

## 0.5 Parameter provenance (a priori confirmation — binding)
All frozen parameters chosen a priori. No PnL examined, no OOS viewed, no
parameter-combination comparison. Premium-index data has **not** been fetched for
signal use or inspected for distribution; only a retention/depth probe (earliest bar,
bar count) was run to confirm the 36-month test is feasible — no premium values were
read into a signal. Every non-sign parameter is inherited verbatim from the
already-registered T4 spec (universe, quintiles, 3-day lookback, 3-day rebalance,
fill model, walk-forward, null, Bonferroni) precisely so this thesis differs from T4
in exactly one place: the signal.

## 1. Economic justification — why divergence should predict future returns

Funding is a **clamped, time-averaged, interest-adjusted, discretely-settled** transform
of the premium index. The premium index is the **raw, continuous, unclamped** basis =
real-time net leverage demand. Their difference

```
divergence = trailing-mean(premium_index)  −  trailing-mean(funding_rate)
```

is the portion of leverage-demand pressure the funding mechanism **fails to transmit**
to position holders. It is ~zero for calm names and grows precisely when demand is
extreme enough to (a) hit the funding clamp, or (b) move faster than the 8h settlement
can average in. Two mechanisms give it predictive content — and they point opposite
ways, which is why both signs are registered:

- **B1a — contrarian (hidden crowding / under-charged risk):** large **positive**
  divergence ⇒ perps trade richer than funding is charging ⇒ crowded longs are NOT
  paying the full price of their crowding ⇒ the position is more unstable than the
  (falsified) funding rate reveals ⇒ a stronger squeeze/reversion is expected.
  **SHORT** the high-divergence quintile, **LONG** the low-divergence quintile.

- **B1b — continuation (demand acceleration / lead-lag):** the premium index **leads**
  the lagged 8h-settled funding rate; a large positive divergence ⇒ leverage demand is
  accelerating ahead of what funding has settled ⇒ near-term continuation as the basis
  keeps building. **LONG** the high-divergence quintile, **SHORT** the low.

Because the signal subtracts the funding level, neither story is reachable from the
funding rate alone — the predictive content, if any, is exactly what T4 could not see.
The incremental signal concentrates in the **clamped / fast-moving tail**, which is
sparse, so the **honest prior is low-to-moderate** — but the test is genuinely
orthogonal to T4, not a relabeling of it.

## 2. Data (free, verified available — fetch required, no purchase)
- **Premium index** (new): Binance `premiumIndexKlines`, **8h** interval, U30, 36mo —
  probe-confirmed retained to 2019-12 (majors) / listing date (alts); 1109 daily bars
  BTC over the window; no 30-day cap. Fetched via an extension to `fetch_perp_data.py`
  (mechanical acquisition only; **no distribution inspection before registration**).
- **Funding** (on disk): `*_funding_u30.parquet`, 8h, 36mo, 171 syms.
- **Price** (PnL, on disk): `*_1h_perp_u30.parquet`.
- **Universe** (on disk): `u30_universe_daily.parquet` (point-in-time).
- **Paid data required:** NONE. No OI / liquidation / depth.
- **Corrupt-row rule (FROZEN, in params_hash):** at load, exclude any row with
  **year > 2100**, then clip to [2023-05-28, 2026-05-27]. Applied to the premium panel
  too. No other filtering.

## 3. FROZEN PARAMETERS (one value each; justification each)

| Parameter | Frozen value | Justification (one line) |
|---|---|---|
| **Universe** | point-in-time U30 (top-30 by 30d median quote vol, onboard ≤ t−90d, no survivorship filter) | inherited from T4 — identical cross-section so the only change vs T4 is the signal. |
| **Signal** | trailing **premium-index mean − trailing funding mean** (the divergence) | isolates leverage-demand pressure NOT expressed by the falsified funding rate. |
| **Premium measure** | mean of last **9** `premiumIndexKlines` 8h closes strictly before t | 3 days at 8h cadence — matched exactly to the funding window for a clean difference. |
| **Funding measure** | mean of last **9** funding settlements strictly before t | identical 3-day/9-settlement window as T4; same cadence as premium for unit-aligned subtraction. |
| **Lookback** | **3 days** (9 × 8h) for both legs | inherited from T4; aligns premium and funding cadences so the divergence is dimensionally clean. |
| **Threshold** | cross-sectional **quintiles**: extreme top 6 / bottom 6 of ranked divergence | inherited from T4; rank-based extremity, self-calibrating, parameter-free. |
| **Sign — B1a** | SHORT high-divergence quintile, LONG low-divergence quintile | contrarian: hidden under-charged crowding reverts. |
| **Sign — B1b** | LONG high-divergence quintile, SHORT low-divergence quintile | continuation: premium leads funding, demand keeps building. |
| **Holding period** | **3-day** rebalance, full re-rank 00:00 UTC, hold = lookback | inherited from T4; measure-horizon = resolution-horizon. |
| **Hysteresis / stops** | none | inherited from T4; the re-rank is the exit. |
| **Portfolio** | $100 book, equal-dollar legs, dollar-neutral | inherited from T4. |
| **Fees** | taker 5 bps/side on \|Δnotional\| | inherited from T4. |
| **Fill model** | half_spread_bps=5.0, impact_coef_bps=10.0 | inherited from T4 (approved 2026-06-09). |
| **PnL source** | price move (NOT funding income, NOT basis carry) | the bet is on the price path of divergent names. |
| **Window** | 2023-05-28 → 2026-05-27 (36 mo) | inherited from T4. |
| **Corrupt-row rule** | exclude year > 2100, then clip to window | inherited from T4; in params_hash. |
| **Walk-forward** | 4mo train / 2mo OOS / 2mo step, anchored, non-overlapping, ≥15 folds | inherited from T4. |

## 4. Acceptance gate (5-part, frozen — `xsect_walkforward.evaluate`)
ALL FIVE required; 4/5 = FAIL; no partial credit, no re-runs.
1. OOS net > 0 in ≥ 60% of folds
2. median per-fold OOS Sharpe ≥ 0.50 (per-trade, √60)
3. pooled-OOS daily Sharpe ≥ 1.0 (√365)
4. worst single-fold maxDD ≤ 20%
5. **null control:** pooled-OOS Sharpe > **97.5th** percentile (Bonferroni, B1a+B1b)
   of the registered null, 1000 draws, seed=7

- **Null model (frozen):** random-quintile selection — same rebalance dates, same
  6-per-side counts, same 3-day turnover, names drawn uniformly from the day's eligible
  U30 (`null_engines.null_distribution`). Identical fee + slippage load.
- **No economics pre-check:** PnL is price-driven; no funding-income void check applies.

## 5. Pass / kill criteria
- **PASS (either thesis):** all 5 met → STOP, report verdict + null p-value + params-hash;
  recommend re-privatize repo + a realistic-fill forward soak. No live capital.
- **KILL (default):** one FAIL → archive that thesis permanently. No re-tune, no sign-flip
  "fix" (the other sign is its own registered thesis). A full B1a+B1b FAIL extends the
  falsification boundary to "premium index carries no incremental information beyond
  funding" — a clean, high-information outcome.

## 6. Frozen specification hashes (params_hash)
SHA-256 over the canonical sorted frozen-parameter object (§2 corrupt-row rule + §3 + §4),
first 12 hex. Any change to any frozen value changes the hash and voids registration.

- **B1a (contrarian)** params_hash: **`fa760fe0671c`**
- **B1b (continuation)** params_hash: **`2f42c62e7c71`**

(Differ only by `sign_convention` — proof the sole registered difference is the sign.)

## 7. Run record (filled AFTER registration + run — empty now)
- Registration commit SHA: `<pending — this file's commit>`
- Data fetch: extend `fetch_perp_data.py` for `premiumIndexKlines` 8h, U30 (post-commit).
- B1a command: `.venv-nt/Scripts/python tools/nautilus/run_b1_basis_divergence.py --thesis a`
- B1b command: `.venv-nt/Scripts/python tools/nautilus/run_b1_basis_divergence.py --thesis b`
- Verdict JSONs: `data/graduation/B1a_basis_funding_divergence_<date>.json`, `…B1b…`

---
*Finalized 2026-06-09. NOT registered until committed. No premium data fetched for
signal use; no signal or PnL computed.*
