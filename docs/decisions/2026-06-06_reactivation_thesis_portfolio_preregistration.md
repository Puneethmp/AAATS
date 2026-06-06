# 2026-06-06 — Reactivation Research Program: Pre-Registered Thesis Portfolio

> **REGISTERED — commit `5a2c33664c1687b711827b3c57d4c1df4fabdfce` (2026-06-06) is the
> pre-registration timestamp.** All frozen parameters in §3 are sealed as of that commit.
> Any data, signal, or PnL work in this program post-dates it. (Header recorded in this
> follow-up commit per §7.)
>
> **STATUS: REGISTERED (committed `5a2c3366`).**
> Per the reactivation clause in CLAUDE.md, this document is the NEW pre-registered thesis
> (portfolio) required to reopen any strategy research. **Pre-registration integrity rule:
> this file must be committed to origin/main BEFORE any backtest, data exploration beyond
> infrastructure verification, or signal computation occurs.** The commit SHA becomes the
> registration timestamp. Authored in a Cowork session (cannot commit from sandbox — git
> index.lock gotcha #4); first action of the next Claude Code session is to commit this file
> unmodified.
>
> Operator authorization: 2026-06-06 Cowork session. Operator explicitly accepted that
> optimizing leverage/sizing/risk/frequency cannot create expectancy, prohibited rebuilding
> C1/C3/C6/TSMOM, and directed a new-edge-discovery program with falsification-first design.

## 0. Scope and non-goals

**Goal:** find a statistically defensible source of alpha in crypto markets that survives
null-controlled, out-of-sample, multi-regime validation — or falsify the candidate families
cheaply and definitively.

**Non-goals (hard):** no modification or re-testing of C1/C3/C6/C7/TSMOM logic; no leverage
work; no live-flip of anything; no infra beyond the minimum needed to test these theses;
no paper-soak changes (D.5 research bed continues untouched).

**Terminal semantics:** each thesis gets exactly ONE harness run against its frozen criteria.
PASS → eligible for the next stage (extended paper validation, separately specced).
FAIL → thesis closed permanently; no re-parameterization, no "v2" of the same mechanism
without a materially different economic rationale registered as a new thesis.

## 1. The falsification boundary (what is already closed)

Closed by `2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md` and the B.1.5/Track F
program: **time-series directional signals derived from own-price OHLCV on the 6-symbol
major/blue-chip universe (BTC/ETH/SOL/LINK/AVAX/DOT) at 1h–14d horizons** — mean-reversion
(C3 + gate variants v1/v2/v3), absolute momentum (TSMOM L=336h), band/range (C6), single-pair
stat-arb (C1), their ensembles (EW + inverse-vol) — plus **major-pair spot+perp funding carry
at ~19.5h median hold** (C7, fee-bound 22:1, structural).

Explicitly NOT closed (cited as untested in the decision docs themselves):
cross-sectional (relative-rank) construction of any kind; funding signals on the alt-perp
cross-section; perp-only carry structures (C7's bind was the 20bps spot leg);
positioning/flow data families (OI, liquidations, orderbook); maker-side execution;
event-driven; market-making. These are the candidate space.

## 2. Candidate family scoring

Scoring axes per operator directive. Edge potential = prior probability a real, fee-paying
edge exists at our scale. IV = expected information value = P(edge) × value-if-true ÷ cost-to-test.

| Family | Edge potential | Data availability | Impl. complexity | Capacity @ $200–$5k | Fee sensitivity | IV rank |
|---|---|---|---|---|---|---|
| T1 Cross-sectional alt-perp funding dispersion (perp-only carry) | Medium (structural payer-of-leverage mechanism; documented persistence) | HIGH — same Binance FAPI endpoint already used; expand symbol list | LOW-MED — extend `fetch_perp_data.py`, adapt C7 ledger to basket | Fine (alt-perp depth ≫ our size) | LOW if hold ≥3d (perp 5bps taker legs) | **1** |
| T2 Cross-sectional momentum, weekly, alt universe | Low-Medium (documented in crypto cross-section academically; price-derived → closest to closed boundary) | HIGH — same klines as T1 (shared build) | LOW — direct reuse of walk-forward harness | Fine | LOW (weekly turnover) | **2** |
| T3 OI/positioning crowding extremes | Unknown-Medium (new data family, genuine information) | **LOW — Binance OI history ≈30d only; historical requires purchase or forward collection** | LOW once data exists | Fine | MED | **3 (data-gated)** |
| T4 Liquidation-cascade reversion | Medium mechanism, **but historical liquidation feed not freely available** (Binance force-order endpoint retired; websocket is sampled, real-time only) | LOW | MED | Fine | HIGH (taker entries in fast markets) | 4 (folded into T3 data program) |
| T5 Passive market-making / spread capture | Medium | n/a (needs L2 + queue-position simulation; honest offline validation near-impossible) | HIGH | Fine | n/a (maker rebate IS the model) | 5 — **not pursued** |

Funded now: **T1 + T2** (shared data build, one infra pass). Registered but data-gated: **T3**
(forward collector starts now; test when ≥9 months collected or historical data purchased).
T4 merges into T3's data program. T5 rejected on validation-honesty grounds.

## 3. Thesis specifications (FROZEN)

Parameters below are frozen at registration. Any change before the harness run voids the
registration; any change after a FAIL is a new thesis requiring a new registered mechanism.

### Common to T1/T2

- **Universe U30:** Binance USDT-M perpetuals, point-in-time: at each rebalance date t, all
  symbols with onboardDate ≤ t − 90d, ranked by trailing 30d median daily quote volume,
  top 30, EXCLUDING symbols delisted ≤ t (delisted symbols remain in history until their
  delist date — no survivorship filtering by today's listing status). BTC/ETH included
  (ranks will marginalize them naturally).
- **Data:** 1h perp klines + full 8h funding history, 2023-05-28 → 2026-05-27 (36 months,
  matching the Track F window), via extended `tools/backtest/fetch_perp_data.py`.
- **Fees:** Binance USDT-M VIP-0 **taker 5bps both sides** on every leg (conservative; no
  maker assumption). Funding settled per actual historical 8h prints, sign-correct per side.
- **Book:** $100 fixed, equal-dollar legs, dollar-neutral long/short at construction
  (residual beta measured and reported, not optimized).
- **Walk-forward:** identical fold geometry to Track F — 4mo train / 2mo OOS / 2mo step,
  ≥15 folds over 36 months, anchored, non-overlapping OOS.
- **Acceptance gate (5-part, frozen, reused from Track F):**
  1. OOS net > 0 in ≥60% of folds;
  2. median per-fold OOS Sharpe ≥ 0.50 (per-trade, √60);
  3. pooled-OOS daily Sharpe ≥ 1.0 (√365);
  4. worst single-fold maxDD ≤ 20%;
  5. **null control:** pooled-OOS Sharpe > **97.5th percentile** of the thesis's null
     distribution (1000 draws, seed=7). p97.5 not p95: Bonferroni adjustment for testing
     two theses in this registration (family-wise α = 5%).
  ALL five required. 4/5 = FAIL. No partial credit, no re-runs.
- **Null models (per thesis, defined below):** must preserve trade count, rebalance dates,
  position sizes, and turnover of the real strategy — randomizing ONLY the selection — so
  the null carries identical fee load.

### T1 — Cross-sectional alt-perp funding dispersion basket (perp-only carry)

- **Economic mechanism:** perp funding is the price of leverage demand. Extreme positive
  funding = crowded longs paying shorts; extreme negative = crowded shorts paying longs.
  A dollar-neutral basket short the highest-funding quintile and long the lowest-funding
  quintile collects funding from both sides while market beta nets out. Distinct from C7:
  no spot leg (C7's 20bps structural bind), cross-sectional not single-pair, and turnover
  is rank-driven (days–weeks) not threshold-driven (hours).
- **Signal (frozen):** trailing mean funding rate over 21 settlements (7d), per symbol,
  ranked across U30 at 00:00 UTC daily.
- **Portfolio (frozen):** short top quintile (6 names), long bottom quintile (6 names),
  equal dollar. **Hysteresis:** a held name exits only when it leaves the extreme **tercile**
  of its side, or at 21d max hold. New entries only from the extreme quintile. (Band gap
  exists to suppress churn; both bands frozen here.)
- **Economics pre-check (registered, run BEFORE the harness, allowed):** measure the
  distribution of selected-quintile |funding| over the window. If the median selected name
  accrues < 10bps net funding per average holding period (i.e. cannot pay 10bps round-trip
  taker even in expectation), the thesis is declared **economically void without a harness
  run** — same terminal standing as a FAIL. This pre-check reads funding data only (no PnL,
  no price-based tuning) and is the single permitted look at the data before the run.
- **Null model:** random-quintile selection — same dates, same counts per side, same
  hysteresis mechanics, names drawn uniformly from U30; 1000 draws.
- **Min sample:** ≥300 pooled OOS round trips across folds; if turnover is so low the count
  falls short, the gate still runs but the verdict is capped at "insufficient-n FAIL."

### T2 — Cross-sectional momentum, weekly rebalance, alt universe

- **Economic mechanism:** relative (not absolute) momentum across the alt cross-section —
  winners-minus-losers, the construction documented in crypto academic literature and
  explicitly absent from the falsified set (TSMOM was time-series sign on 6 majors with
  daily rebalance). Dollar-neutral L/S removes the market-direction bet that killed TSMOM.
- **Signal (frozen):** trailing 21d return SKIPPING the most recent 24h (reversal guard),
  per symbol, ranked across U30 each Monday 00:00 UTC.
- **Portfolio (frozen):** long top quintile, short bottom quintile, equal dollar, weekly
  full rebalance, no intraweek action, no stops (the weekly re-rank IS the exit).
- **Null model:** random-rank quintiles — same dates, same counts, same weekly turnover;
  1000 draws.
- **Min sample:** ~156 rebalance weeks × 12 names; pooled OOS position-weeks ≥ 1000.
- **Honesty note (registered):** T2 is the closest of the portfolio to the falsified
  boundary (price-derived). It is funded because its marginal cost on top of T1's data
  build is near zero and a clean FAIL extends the falsification boundary to cross-sectional
  construction — high information value either way.

### T3 — Positioning crowding (OI + forced-flow) — REGISTERED, DATA-GATED

- **Economic mechanism:** rapid OI expansion against stagnant price = crowded leverage
  vulnerable to squeeze; OI flush + extreme funding swing = forced deleveraging overshoot →
  short-horizon reversion. Uses information genuinely absent from OHLCV.
- **Data program (build now, cheap):** box-side cron collector snapshotting
  `/fapi/v1/openInterest` (plus premium index) hourly for U30 into append-only SQLite —
  ~30 lines on the existing cron stack. Liquidation websocket (sampled forceOrder stream)
  logged opportunistically on the same collector. **No backtest until ≥9 months collected,
  or operator approves purchasing historical OI/liquidation data (e.g. Coinglass/Laevitas;
  decision deferred — cost unknown at registration).**
- **Signal family registered (parameters to be frozen in an addendum BEFORE its harness
  run, after data exists but before any signal/PnL computation):** OI z-score vs own 30d
  history crossed with price-drift divergence; event-study entry on flush days.
- **Gate:** same 5-part structure; null = shuffled event dates (same event count, same
  hold); threshold p97.5 if tested alone, re-Bonferroni'd if tested alongside another thesis.

## 4. Anti-snooping protocol (binding)

1. This document is committed BEFORE any data beyond the T1 economics pre-check is touched.
2. One harness run per thesis, seed=7, results committed verbatim (PASS or FAIL) to
   `data/graduation/` + a decision memo, same as Track F.
3. No parameter sweeps. The frozen parameters above are the only configuration ever run.
   Dev/debug work uses fold 0's train window ONLY (2023-05-28 → 2023-09-28) with synthetic
   or truncated data; OOS folds are never opened before the registered run.
4. Multiple-testing control: Bonferroni across simultaneously-tested theses (T1+T2 → p97.5).
5. Any code bug discovered post-run that affected the verdict → fix, document, re-run ONCE
   with the same frozen parameters, both results reported.
6. A PASS does not authorize live trading. It authorizes a separately-specced extended
   validation stage (forward paper, capacity/slippage study, operator GO gate).

## 5. Minimal infrastructure build (the ONLY construction authorized)

| Item | Scope | Effort |
|---|---|---|
| Extend `fetch_perp_data.py` | CLI symbol-list + date-range args; U30 universe resolver with point-in-time onboardDate; klines + funding for ~30 symbols × 36mo | ~1 session |
| Basket ledger | Adapt C7's per-pair ledger to N-leg dollar-neutral basket accounting in the NT/direct harness | ~1 session |
| Null engines | Rank-shuffle + random-quintile nulls (generalization of existing sign-shuffle) | small |
| T3 collector | Box cron: hourly OI + premium index snapshots, append-only SQLite, L10-style disk guard | ~30 lines |

Explicitly NOT built: orderbook/L2 capture, liquidation historical backfill, multi-exchange
fetchers, any live-execution path, any leverage machinery.

## 6. Ranked portfolio and execution order

1. **T1 funding dispersion** — run first: highest prior, structural mechanism, fee math
   pre-checkable, exits cheaply via the economics pre-check if void.
2. **T2 cross-sectional momentum** — runs on T1's data in the same session; near-zero
   marginal cost; clean information either way.
3. **T3 positioning crowding** — collector starts immediately; test in ≥9 months or on
   data purchase; parameters frozen by addendum before its run.

Expected program cost: 2–3 Claude Code sessions for T1+T2 end-to-end (data → harness → verdict
memos). Honest prior: P(at least one PASS) ≈ 25–35%. A full-portfolio FAIL is a valid,
valuable outcome: it extends the falsification boundary to carry and cross-sectional families
and the research bed continues with its conclusion strengthened.

## 7. Registration checklist (next Claude Code session, in order)

- [ ] Commit this file unmodified to origin/main (auto-rebase first; commit SHA = registration).
- [ ] Build §5 infrastructure (no signal computation).
- [ ] Run T1 economics pre-check; commit its output verbatim.
- [ ] If pre-check passes: run T1 harness once; commit verdict.
- [ ] Run T2 harness once; commit verdict.
- [ ] Deploy T3 collector to box (deploy_lib discipline).
- [ ] Write decision memo(s); update CLAUDE.md program status ONLY if a PASS occurs.
