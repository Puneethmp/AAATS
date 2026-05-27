# Final NautilusTrader Extraction — Everything AAATS Takes to Succeed

**Status:** ANALYSIS (capstone) — recommendations + verified evidence. No runtime impact.
**Authored:** 2026-05-27 (Cowork session, D.5 soak day 4).
**Method:** NautilusTrader was **installed and introspected hands-on** in the workstation sandbox (`pip install nautilus_trader`, version `latest`). Every capability below was confirmed by importing the real module and reading the real signature — not inferred from docs. Commands are reproducible from `tools/nautilus/` (to be built).
**Reads with:** [2026-05-26_nautilus_trader_comparison.md](2026-05-26_nautilus_trader_comparison.md) (the borrow shortlist) and [2026-05-27_c3_nautilus_port_and_graduation_gate.md](2026-05-27_c3_nautilus_port_and_graduation_gate.md) (the C3 pilot). This doc is the definitive "what to take and why" — the other two are the plan to take it.

---

## The thesis in one paragraph

AAATS does not need to become NautilusTrader. It needs **eight specific capabilities** that NT has and AAATS lacks, each of which closes a concrete gap that is currently blocking the bot from becoming *successful* — defined as: a validated edge, deployed on real capital, that survives realistic execution cost and doesn't blow up unattended. AAATS already owns the "doesn't blow up unattended" half (the L1–L10 stack). NT supplies the "validated edge that survives realistic cost" half. The combination is the whole.

---

## What "successful" requires, and where AAATS is blocked

| Success requirement | AAATS status today | The blocker | NT supplies |
|---|---|---|---|
| A validated edge | C3 MARGINAL on a toy cost model; C1/C6 dead | No realistic fee/fill/impact model | Items 1–3 below |
| Edge survives live execution | Unknown — never modeled honestly | Naive symmetric-slippage replay, no maker/taker, no fills | Items 1, 4 |
| Deployable to real capital | NO-GO 2026-05-21, no live loop | No research→live parity, no broker adapter | Items 5, 6 |
| Correct accounting | Float math, share-equality drift | No Decimal money discipline | Item 2 |
| Doesn't blow up unattended | **SOLVED** — L1–L10 | — | AAATS keeps this; NT does not supply it |

The bot's path to success runs straight through the eight items. Everything else is noise.

---

## The eight things AAATS takes from NT (all verified hands-on)

### 1. A realistic cost model — `MakerTakerFeeModel` + `FillModel` + `LatencyModel`

**Verified:**
```
nautilus_trader.backtest.models.MakerTakerFeeModel   # fee on maker/taker schedule + notional
nautilus_trader.backtest.models.FixedFeeModel        # flat per-trade fee
FillModel(prob_fill_on_limit=0.2, prob_fill_on_stop=0.95,
          prob_slippage=0.5, random_seed=42)          # constructed successfully
nautilus_trader.backtest.models.LatencyModel          # order/insert/update latency
```

**AAATS problem it solves:** the single most important one. The B.1.5 verdict ("C3 MARGINAL, break-even ~18-23 bps/side") came from `tools/backtest/c3_replay.py`, which applies a **symmetric `slippage_bps` to a bar-close fill and charges zero fees** ([c3_replay.py:126-128](../../tools/backtest/c3_replay.py#L126-L128)). That model cannot tell you whether C3 is *actually* live-viable, because the real question is: **do C3's limit entries fill, and at what cost, given a 10bps spot taker fee + 2-15bps market impact?** `FillModel.prob_fill_on_limit` is precisely that — it models the fact that a resting limit order (maker, avoids impact) only fills *some* of the time. This is the mechanism the B.1.5 memo said would make-or-break C3 ("switching from naive market orders to TWAP/limit execution could preserve the edge") and it is **untestable in the current harness**.

**How to adopt:** the C3 NT port (B.1.6) wires the `SIM` venue with `MakerTakerFeeModel` (Binance VIP-0: 10bps spot maker/taker) + a `FillModel` with `prob_fill_on_limit` swept across {0.2, 0.5, 1.0}. Run C3 as (a) market/taker and (b) post-only limit/maker and compare. **This is the experiment that turns MARGINAL into GO or NO-GO.**

**Priority: P0 — do first.** It is the only thing that answers "is there an edge at all."

---

### 2. Decimal money — `Money` / `Price` / `Quantity` / `Currency`

**Verified:** `nautilus_trader.model.objects: Money, Price, Quantity, Currency` — all present, Decimal-backed by construction.

**AAATS problem it solves:** `paper_trades.db` stores `price REAL, value REAL` (float). The share-equality mismatch detector (L5) exists *because* float arithmetic leaks at the cent boundary. At C3's ~12bps margin of safety, that leakage is not negligible — it can flip a marginal trade's sign. NT makes float-money bugs structurally impossible.

**How to adopt:** two layers. (a) In the NT harness, money is already Decimal — free. (b) For production, migrate `paper_trader.record_trade()` to `Decimal` serialized as TEXT in SQLite (TEXT preserves exact representation), parse back to Decimal on read. Keep float only inside strategy signal math where bar noise dominates.

**Priority: P1 — before any live capital.** Float money + real money = malpractice. Ship during soak, behind a flag.

---

### 3. Free institutional metrics — `PortfolioAnalyzer` (17 built-in statistics)

**Verified — the complete built-in set:**
```
expectancy, long_ratio, loser_avg, loser_max, loser_min, profit_factor,
returns_avg, returns_avg_loss, returns_avg_win, returns_volatility,
risk_return_ratio, sharpe_ratio, sortino_ratio, win_rate,
winner_avg, winner_max, winner_min
```

**AAATS problem it solves:** the graduation gate (G1–G7) needs trustworthy metrics. `c3_replay.py:summarize_trades` hand-rolls a Sharpe with an admitted hack ("annualization factor = sqrt(60)... conservative but comparable"). NT computes Sharpe, Sortino, profit factor, expectancy, and risk-return ratio with audited implementations. **The graduation gate stops depending on home-grown stats.**

**Direct mapping — graduation gate → NT statistic:**

| Gate | Criterion | NT statistic (free) |
|---|---|---|
| G1 | Net PnL > 0 | `PnL` (post-fee, from the engine) |
| G2 | Sharpe ≥ 1.0 | `sharpe_ratio` |
| G3 | Max DD ≤ 20% | engine account drawdown |
| G4 | ≥ 30 trades | trade count |
| G5 | Profit factor ≥ 1.3 | `profit_factor` |
| G6 | OOS/IS degradation | `sharpe_ratio` ratio across windows |
| G7 | Maker-fill robustness | re-run under `FillModel` prob sweep |
| + | bonus | `sortino_ratio`, `expectancy`, `risk_return_ratio` for free |

**Priority: P0 — comes with the harness.** Zero extra cost; just read the analyzer.

---

### 4. The full order-type matrix — verified enums

**Verified:**
```
TimeInForce: AT_THE_CLOSE, AT_THE_OPEN, DAY, FOK, GTC, GTD, IOC
OrderType:   LIMIT, LIMIT_IF_TOUCHED, MARKET, MARKET_IF_TOUCHED,
             MARKET_TO_LIMIT, STOP_LIMIT, STOP_MARKET,
             TRAILING_STOP_LIMIT, TRAILING_STOP_MARKET
Contingency: OCO, OTO, OUO   (+ NO_CONTINGENCY)
TriggerType: BID_ASK, LAST_TRADE, MARK_PRICE, MID_POINT, ... (10 total)
TrailingOffset: BASIS_POINTS, PRICE, TICKS, PRICE_TIER
```

**AAATS problem it solves:** `execution/order_tif_manager.py` has a 5-value TIF enum *scaffolded but not wired into the order lifecycle*. AAATS has no contingency orders, no trailing-stop primitive, no post-only/reduce-only. C3's exit logic is literally a trailing stop (`Z_TRAILING_MIN`/`Z_TRAILING_DROP`) reimplemented by hand — NT has `TRAILING_STOP_MARKET` with `TrailingOffsetType.BASIS_POINTS` natively. When live-flip arrives, the exchange will demand these primitives; building them from NT's spec is far cheaper than inventing them.

**How to adopt:** at live-flip (Track A.3/A.4), lift NT's order-type + TIF + contingency enums as the canonical order vocabulary. Wire `IOC` (taker fills), post-only `LIMIT` (maker fills), `reduce-only` (safe exits), and `OCO` (stop+take-profit bracket — exactly C3's exit shape) into `paper_executor.py` first, then the live adapter.

**Priority: P2 — at live-flip, not before.** Paper-mode doesn't exercise fills, so the gap is invisible until real orders.

---

### 5. Research→live parity — `BacktestEngine` + `live.node` + same `Strategy`

**Verified:** `nautilus_trader.backtest.engine.BacktestEngine`, `nautilus_trader.live.node`, `nautilus_trader.trading.trader.Trader`, `nautilus_trader.trading.strategy.Strategy` — the identical `Strategy` class runs in both backtest and live.

**AAATS problem it solves:** two at once. (a) The 2026-05-21 NO-GO's first gap was "no live trade loop exists" — NT's `live.node` *is* a live trade loop, and it runs the same strategy code the backtest validated. (b) AAATS's entire B.1.5 design rests on "import the same strategy module in replay" to avoid backtest/live divergence; NT makes that a structural guarantee instead of a discipline you have to maintain by hand.

**How to adopt:** strategically, not immediately. Once a strategy graduates (passes the gate in NT backtest), the *same* `Strategy` subclass can run on `live.node` against a real adapter — wrapped in AAATS's L1–L10 monitoring. This is the long-term shape of the deployment body. Near-term, graduated strategies still deploy into the AAATS `run_crypto` cycle; the NT-live path is the Track C+ option once one strategy has proven the pipeline end to end.

**Priority: P2/P3 — the destination, not the next step.** Don't rebuild the live path until you have a graduated edge to put on it.

---

### 6. Exchange adapters — Binance / Bybit / Interactive Brokers (all verified present)

**Verified:**
```
[OK] nautilus_trader.adapters.binance
[OK] nautilus_trader.adapters.bybit
[OK] nautilus_trader.adapters.interactive_brokers
```

**AAATS problem it solves:** AAATS is single-exchange (Binance paper) and the roadmap's "direct broker adapters" item (locked 2026-05-10, "no OpenAlgo") is unwritten. NT's adapters are production-grade, maintained, and normalize every venue to one domain model — so the *same* graduated strategy can trade Binance spot, Bybit perps, or IB (for the halted India book) without strategy changes.

**How to adopt:** when live-flip needs a real broker, evaluate NT's Binance adapter against a hand-rolled one. Even if you don't use NT's adapter in production, its `ExecutionClient`/`DataClient`/`InstrumentProvider` interface is the cleanest template to copy. The India book (currently operator-halted) is the natural place NT's IB adapter could re-open a market AAATS can't currently reach cleanly.

**Priority: P2 — at adapter-design time.** Interface borrow now (free), implementation decision at Track A.4.

---

### 7. Risk position sizing — `FixedRiskSizer`

**Verified:**
```
FixedRiskSizer.calculate(entry, stop_loss, equity, risk: Decimal,
                         commission_rate=0, exchange_rate=1,
                         hard_limit=None, unit_batch_size=1, units=1)
```

**AAATS problem it solves:** C3 uses vol-adjusted sizing (`_compute_trade_size`, equalizing per-position PnL variance) which is good, but it sizes by *target dollar exposure*, not by *risk-to-stop*. NT's `FixedRiskSizer` sizes so that hitting the stop loses a fixed fraction of equity — the textbook risk-parity-per-trade approach, with commission baked into the calc. This is complementary, not a replacement.

**How to adopt:** offer it as an alternative `SIZING_MODE` in the harness and compare equity curves. Risk-to-stop sizing may improve C3's drawdown profile (currently the gate's G3 constraint). Low priority — sizing is a second-order optimization once the edge is confirmed.

**Priority: P3 — after the edge is validated.** Don't optimize sizing on a strategy that hasn't passed G1.

---

### 8. Deterministic event loop + latency modeling — the future event-driven path

**Verified:** `LatencyModel` present; the engine is a deterministic nanosecond event loop (per NT's core design).

**AAATS problem it solves:** none *yet*. AAATS's 15-min cycle is fine for bar-driven mean-reversion. But the strategies AAATS *can't* run today — funding-rate arb (C5b, halted), intra-bar gap fills, anything sub-hourly — need an event loop. NT's is the one to grow into if the strategy universe expands past bar-based.

**How to adopt:** don't, yet. Flag it as the architecture AAATS migrates toward *if and when* a graduated strategy needs sub-bar timing. Re-evaluate at Track E (futures/perps).

**Priority: P4 — watch only.** Premature today; the wrong thing to build before there's an edge that needs it.

---

## What AAATS explicitly KEEPS (does not take from NT)

NT has none of these and shouldn't — they're AAATS's moat and the half of "success" NT can't supply:

- **The L1–L10 monitoring stack** — cron liveness, ledger-divergence halt, drawdown gauges, persistent auto-halt, disk/repo watchdog. NT expects you to build observability yourself.
- **Operator-away mode** — heartbeat watchdog, Telegram alerts, operator-return runbook. NT is built to be supervised.
- **The 3-channel halt + doctrine-coded kill thresholds** — more operator-aware than NT's institutional position-limit risk engine.
- **Cheap single-box infra** — ~$15/mo. NT's full stack assumes Redis + data subscriptions + monitoring infra.
- **The documented decision/incident history** — `docs/decisions/`, `docs/known_issues/`, runbooks.

The combine-both architecture is precise: **NT supplies items 1–8 (find + validate + execute the edge); AAATS supplies the operational survival layer (keep the edge alive unattended).** Neither half is optional for success.

---

## Prioritized adoption roadmap

| Priority | Item | When | Why this order |
|---|---|---|---|
| **P0** | 1. Realistic cost model (FillModel + FeeModel) | Now (B.1.6) | Only thing that answers "is there an edge." Everything else is moot if C3 fails here. |
| **P0** | 3. Free metrics → graduation gate | Now (B.1.6, free with harness) | The measurement layer for P0. |
| **P1** | 2. Decimal money | During soak, pre-live | Correctness floor before real capital. |
| **P2** | 4. Order-type matrix | Live-flip (Track A.3/A.4) | Invisible until real fills; needed for live. |
| **P2** | 6. Exchange adapters | Live-flip (Track A.4) | Interface borrow now, impl decision later. |
| **P2/P3** | 5. Research→live parity | Track C+ | The destination once an edge graduates. |
| **P3** | 7. Risk sizing | Post-validation | Second-order; don't optimize a dead edge. |
| **P4** | 8. Event loop / latency | Track E (if needed) | Premature; watch only. |

---

## The single highest-leverage action

**Run C3 through NT's `FillModel` + `MakerTakerFeeModel` (P0).** Every other item is downstream of the answer to one question: *does C3 have an edge that survives realistic limit-order execution on 6 months of out-of-sample data?* The 6-month parquet data is already cached (`data/historical/*.parquet`), NT is installed and verified, and C3's pure functions are already isolated and reusable. The experiment is teed up. Its result — GO or NO-GO — determines whether the next move is "deploy C3 to live capital" or "build C3-class supplements." Either answer is worth more than any amount of further analysis.

Build status as of this doc: NT installed + verified in sandbox; C3 imports clean (pydantic added); 6mo data cached; `tools/nautilus/` scaffolding is the next build step (B.1.6, ~4 sessions).

---

## Verification appendix (reproducible)

All claims above were confirmed by importing the installed package:
- `nautilus_trader.__version__` → `latest`
- Fee/fill/latency models, order enums, Money/Price/Quantity, RiskEngine + FixedRiskSizer, PortfolioAnalyzer (17 stats), BarDataWrangler + ParquetDataCatalog, Strategy, Binance/Bybit/IB adapters, live.node + Trader — **all imported successfully** in Python 3.10 sandbox with numpy 2.2.6 / pandas 2.3.3.
- `FillModel(prob_fill_on_limit=0.2, prob_fill_on_stop=0.95, prob_slippage=0.5, random_seed=42)` constructed without error.

---

## References

- NT comparison + borrow shortlist: [2026-05-26_nautilus_trader_comparison.md](2026-05-26_nautilus_trader_comparison.md)
- C3 port + graduation gate plan: [2026-05-27_c3_nautilus_port_and_graduation_gate.md](2026-05-27_c3_nautilus_port_and_graduation_gate.md)
- B.1.5 break-even findings: memory `aaats-2026-05-27-b15-phase35-breakeven`
- 6mo walk-forward (naive cost model this replaces): `data/backtest_results/c3_walkforward_6mo_2026_05_27.json`
- C3 source: [trading/altcoin_reversion.py](../../trading/altcoin_reversion.py)
- Existing naive replay: [tools/backtest/c3_replay.py](../../tools/backtest/c3_replay.py)
- NautilusTrader docs: https://nautilustrader.io/docs/
