# 2026-06-06 — Reactivation Program: T1 + T2 verdict — FULL-PORTFOLIO FAIL

> **VERDICT: both funded theses are terminally closed.** T1 (cross-sectional alt-perp
> funding dispersion) is **ECONOMICALLY VOID**; T2 (cross-sectional momentum) is a
> registered-gate **FAIL (1/5)**. No live-flip. CLAUDE.md program status is unchanged
> (a PASS was the only thing that would have moved it). T3 (positioning crowding)
> remains registered + data-gated; its forward collector is now live on the box.

Registration: [2026-06-06_reactivation_thesis_portfolio_preregistration.md](2026-06-06_reactivation_thesis_portfolio_preregistration.md)
(commit `5a2c3366`). Falsification context: [2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md](2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md).

## What was run (per the frozen registration)

One infrastructure pass (pre-reg §5) + one terminal evaluation per funded thesis, no
sweeps, seed=7, raw outputs committed verbatim to `data/graduation/`:

- Point-in-time **U30** universe resolved over 36 months (2023-05-28 → 2026-05-27):
  top-30 Binance USDT-M perps by trailing-30d median quote volume, onboardDate ≤ t−90d.
  Union across all daily rebalances = **171 symbols** (heavy alt-perp rotation).
- N-leg dollar-neutral basket ledger (`tools/nautilus/basket_ledger.py`) generalizing
  the C7 per-pair ledger: daily mark-to-market, real 8h funding per leg, 5bps taker
  per side on |Δnotional| turnover.
- Track-F 5-part gate (`tools/nautilus/xsect_walkforward.py`) with the registered
  Bonferroni **p97.5** null threshold (two theses).

## T1 — funding dispersion: ECONOMICALLY VOID

Raw: [`data/graduation/T1_funding_dispersion_PRECHECK_2026-06-06.json`](../../data/graduation/T1_funding_dispersion_PRECHECK_2026-06-06.json).

The registered **economics pre-check** (funding data only — the single permitted look
before a harness run) measured the funding income the real signal's selected names
actually accrue per holding period:

| metric | value |
|---|---|
| round trips (selected holds) | 1258 |
| **median round-trip funding income** | **8.68 bps** |
| round-trip taker cost (2 × 5bps) | 10.0 bps |
| fraction of holds clearing 10bps | 47.7% |
| mean round-trip funding income | 91.3 bps (skewed by extreme-funding tails) |
| mean hold | 10.4 days |

The **median selected name cannot pay the round-trip taker even in expectation**. Per
the registration (§3 T1: "median < 10bps ⇒ economically void without a harness run —
same terminal standing as a FAIL"), T1 is closed **without** running its harness. The
mean (91bps) confirms a thin tail of extreme-funding names is collectible, but a
6-name equal-weight quintile basket is dominated by its median member, which is
fee-negative. This is the same structural failure mode as C7 (funding income too small
relative to taker fees at our scale), now shown to persist in the **cross-sectional,
perp-only, rank-driven** construction that C7's verdict explicitly left untested.

## T2 — cross-sectional momentum: FAIL (1/5)

Raw: [`data/graduation/T2_xsect_momentum_2026-06-06.json`](../../data/graduation/T2_xsect_momentum_2026-06-06.json).
15 OOS folds, 801 pooled OOS position-weeks, 157 weekly rebalances.

| # | criterion | value | threshold | result |
|---|---|---|---|---|
| 1 | folds OOS net>0 | 66.7% | ≥60% | **PASS** |
| 2 | median per-fold OOS Sharpe | 0.216 | ≥0.50 | FAIL |
| 3 | pooled-OOS daily Sharpe (√365) | 0.857 | ≥1.0 | FAIL |
| 4 | worst single-fold maxDD | 73.9% | ≤20% | FAIL |
| 5 | null control (random-rank) | 0.857 vs p97.5 **0.958** | > p97.5 | FAIL |

ALL FIVE required; **4/5 missed → FAIL**, thesis closed (no re-parameterization).

The signal is **weak but not nothing**: pooled Sharpe 0.857 beats ~95.7% of the 1000
random-rank baskets (empirical p = 0.043; null mean −0.155, std 0.582). It would have
(barely) cleared a single-thesis p95 — but the registration committed Bonferroni p97.5
*before* the run, and 0.857 < 0.958. More decisively, it fails the absolute Sharpe
floors (criteria 2, 3) and suffers a **73.9% drawdown** in the 2026-01→03 fold (the
alt-crash / BTC-dominance window — the same regime that inverted C3-perp in Track 8).
A real, fundable edge cannot post a 74% fold drawdown.

## Interpretation — the falsification boundary, extended

Track F closed time-series own-price directional signals on the 6-major universe.
This program tested the two families those decision docs explicitly named as *open*:

- **Cross-sectional carry** (perp-only funding dispersion) → fee-bound at the median,
  void. The carry-too-small-for-taker bind is now confirmed structural across pair
  (C7) **and** cross-sectional construction.
- **Cross-sectional momentum** (winners-minus-losers, weekly, alt universe) → a weak
  signal that does not clear an honest, Bonferroni-controlled, drawdown-bounded gate.
  The falsification boundary now extends to **cross-sectional construction**, not just
  time-series.

This is a valid and valuable outcome (pre-reg §6 honest prior: P(≥1 PASS) ≈ 25–35%).
The research bed continues with its conclusion strengthened: of every freely-testable
price/funding-derived family at our scale, none has survived. The remaining genuinely
untested signal is **information not in OHLCV+funding** — positioning/flow (T3).

### Survivorship caveat (registered, restated)

The U30 build uses only currently-listed symbols (Binance `exchangeInfo` does not
expose delisted klines). Point-in-time *entry* (onboardDate) is exact; the delist side
could not be reconstructed offline. This bias, if anything, **overstates** alt
robustness (dead alts were typically the worst names), so both terminal verdicts are
only more decisive under it. A future PASS would require sourcing point-in-time
delisted history in the separately-specced extended-validation stage.

## T3 — registered, data-gated, collector now LIVE

`scripts/box/aaats-t3-oi-collector.py` deployed to the box (hourly cron, append-only
`/home/aaats/t3/t3_positioning.db`, L10-style disk guard). First tick captured OI +
premium index for the current top-30 (30/30). **No T3 backtest until ≥9 months are
collected** (≈ 2027-03) or historical OI/liquidation data is purchased; its signal
parameters are frozen by addendum *before* that run (pre-reg §3 T3).

## Disposition

- Live-flip stays OFF. The $25/mo BTC DCA is the only live money. D.5 soak untouched.
- CLAUDE.md program status **unchanged** — no PASS occurred. AAATS remains a monitored
  research bed.
- Reactivation of any *new* thesis still requires its own pre-registered mechanism +
  committed gate. T1 and T2 are closed; re-running either mechanism is not permitted.
- Next dated action: revisit T3 once the collector has ≥9 months (~2027-03).
