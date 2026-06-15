# Pre-Registration — B1: Risk-Managed Cross-Sectional Momentum

> **STATUS: DRAFT — NOT YET FROZEN, NOT YET COMMITTED.**
> Per the program's pre-registration protocol this document and its frozen
> parameters must be (1) reviewed and frozen by the operator, then (2) committed
> to `origin/main` **before any real U30 data is opened**. Opening data before
> this is committed = automatic disqualification (snooping). Code implementing
> this spec lives in `quant/` and has been unit-tested on **synthetic data only**.

## 0. Honesty gate
T2 (raw, taker, net-beta cross-sectional momentum) was **not** a signal-absence
result — it was a near-miss: pooled OOS Sharpe +0.857, beat the null p95 but missed
Bonferroni p97.5 (p=0.043), failed the ≥1.0 Sharpe floor, and took a 73.9%
worst-fold drawdown in an alt-crash window. B1 tests a **different, falsifiable
hypothesis about the same phenomenon**: that T2 failed on *risk construction*, not
predictive content. If B1 also fails the null, cross-sectional momentum is
**permanently closed** (no further variants, ever).

## 1. Hypothesis
**H1:** A risk-adjusted (IR), reversal-skipped cross-sectional momentum signal,
expressed as a dollar-neutral, **beta-neutral, volatility-targeted**, **maker-only**
long/short basket rebalanced monthly, produces — net of realistic maker costs and
funding — a pooled OOS daily Sharpe ≥ 1.0 that exceeds the Bonferroni p97.5 of a
rank-shuffle null, with worst-fold DD ≤ 20%, ≥ 60% folds net-positive, and median
fold OOS Sharpe ≥ 0.50.

**H0:** Under identical risk construction, the basket's OOS Sharpe is
statistically indistinguishable from a rank-shuffled null — the ordering carries no
durable, risk-survivable predictive content at the monthly horizon.

## 2. Frozen parameters (PENDING SIGN-OFF — do not sweep; a sweep voids this)

| Param | Value | Code anchor |
|---|---|---|
| Formation `Lf` | 28 d | `candidates/b1_xs_momentum.FROZEN_PARAMS` |
| Reversal skip `Ls` | 7 d | " |
| Vol lookback | 28 d | `RiskControls.vol_lookback_days` |
| Rebalance | 30 d (monthly) | `PortfolioIntent.rebalance_days` |
| Long / short cut | top / bottom tercile (1/3) | `PortfolioIntent` |
| Beta lookback | 30 d | `RiskControls.beta_lookback_days` |
| Vol target | 15% annual | `RiskControls.vol_target_annual` |
| Max gross leverage | 2.0× | `RiskControls.max_gross_leverage` |
| Max weight / name | 15% of leg | `RiskControls.max_weight_per_name` |
| Maker fee | −2 bps (rebate) | `MakerFillModel.maker_fee_rate` |
| Adverse selection | 3 bps effective half-spread | `MakerFillModel.adverse_selection_bps` |
| Fill prob (base / G7 stress) | 0.8 / 0.5 | `MakerFillModel.fill_prob` |
| Seed | 7 | walk-forward + null |

## 3. Universe
Frozen U30 USDT-M perps (`scripts/box/t3_u30_symbols.txt`, 2026-05-26 snapshot),
Binance, 1h OHLCV + 8h funding via `tools/nautilus/u30_data.py`. Eligibility per
rebalance: full formation+skip history, no >24h gap in the formation window.
**Survivorship caveat:** the frozen list is survivor-biased; survivorship inflates
momentum, so a PASS carries a documented haircut and is *less* trustworthy than a
FAIL. State this in the verdict.

## 4. Construction (implemented + unit-tested in `quant/base/`)
- **Signal** (`ir_momentum_panel`): `score = formation_return / formation_vol`,
  skip most-recent 7d. Tested: ranks a steady low-vol climber above a noisy one.
- **Portfolio** (`RiskManagedConstructor`): inverse-vol legs, **exact**
  beta-neutralization via a 2-scalar solve (preserves gross; small documented
  dollar residual — exact joint dollar+beta neutrality is not attainable with
  leg scalars alone), portfolio vol-target, per-name + gross caps. Tested:
  inverse-vol favors low-vol names; net beta < 0.05; vol hits target or 2× cap;
  caps respected.
- **Execution** (`MakerFillModel`): maker rebate + adverse-selection haircut mapped
  to the ledger's real cost knobs; probabilistic fills drop unfilled names (you
  stay flat, you don't chase). The null applies the identical transform + seed.

## 5. Walk-forward + null (the single committed run)
`tools/nautilus/xsect_walkforward.py`: 15 non-overlapping OOS folds over ≥36 months,
rolling IS window, **seed=7, run exactly once**; OOS folds never inspected before
the run. Null: `tools/nautilus/null_engines.py` rank-shuffle, K=1000, **identical
risk construction applied to the shuffle**, real pooled Sharpe must exceed
**Bonferroni p97.5** (T2 died here — this is the binding criterion).

## 6. Success criteria (ALL required) — `tools/graduation/gate.py`
1. ≥ 60% of 15 folds net-positive.
2. Median fold OOS daily Sharpe ≥ 0.50.
3. Pooled OOS daily Sharpe ≥ 1.0.
4. Worst-fold max drawdown ≤ 20%.
5. Real pooled Sharpe > Bonferroni p97.5 of the rank-shuffle null.
6. Economic sanity: net > 0 after maker costs + funding.
7. G7 maker-robustness: net > 0 at fill-prob 0.5.

## 7. Failure rules (pre-committed, no re-tune)
Any single missed criterion ⇒ **FAIL = terminal**, logged to
`research/falsified.md`. Specifically: fails null ⇒ XS momentum family CLOSED;
passes signal but fails G7 ⇒ "edge exists but not maker-executable at retail
notional" (documented, still FAIL); beats null but misses Sharpe floor ⇒ T2-repeat,
CLOSED at this architecture.

## 8. Promotion on PASS
A clean PASS authorizes the 90-day paper-confirmation stage only (Stage-2 gate:
≥90d, ≥30 live-paper trades on post-research data, live Sharpe ≥ 0.5× backtest OOS,
live DD ≤ worst-fold and ≤15%, slippage ≤ modeled, net>0 reconciled to the cent,
capacity-checked). Paper ≠ live; live is a separate, later, operator-signed step.

## 9. Pre-registered priors
P(pass all) ≈ 15% (10–20%). Most likely informative outcome: a clean FAIL on the
null that closes cross-sectional momentum. B1 is a high-information, low-cost
experiment, not a high-probability route to a deployable edge.

---
**Operator sign-off (required before opening data):**

- [ ] Parameters in §2 reviewed and FROZEN
- [ ] Committed to `origin/main` at commit ________ on ____-__-__
- [ ] Reactivation acknowledged (leaves maintenance mode per `CLAUDE.md`)

Signed: ____________________  Date: __________
