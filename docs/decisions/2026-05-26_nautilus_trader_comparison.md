# NautilusTrader vs AAATS — Comparison & Selective-Borrow Plan

**Authored:** 2026-05-26 (Cowork session, mid-D.5 soak — no runtime impact, docs only).
**Status:** ANALYSIS — recommendations only; nothing ships without operator sign-off.
**Source repo reviewed:** [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) (README + docs/concepts as of 2026-05-26).

---

## TL;DR

NautilusTrader (NT) and AAATS are **not the same kind of product**. NT is a production-grade
trading **engine library**; AAATS is a **deployed personal trading system**. A head-to-head
"which is better" is the wrong frame — NT is better as an engine, AAATS is better as an
unattended-runnable system at <$200 capital with operator-away resilience.

The right question is: **what does NT have that AAATS lacks, and where is the borrow
cheap enough to ship before live-flip?** Four high-ROI borrows, three deferrals, and one
component (NT's backtest engine) that is a serious candidate to **replace the B.1.5
custom replay harness** before that work begins.

---

## What each system actually is

### NautilusTrader (per repo README + docs/concepts)

- **Rust-native core with PyO3 Python bindings.** Python is the control plane (strategy
  logic, config); the engine is compiled Rust. Migration from Cython → PyO3 ongoing.
- **Single deterministic event-driven runtime for research AND live.** Same strategy code
  runs in backtest and production — research-to-live parity is the central design claim.
- **Multi-asset, multi-venue.** Modular adapter pattern; current integrations include
  Binance, Bybit, BitMEX, Deribit, dYdX, Hyperliquid, Kraken, Coinbase International,
  Interactive Brokers, Databento, Betfair, OKX, Polymarket, Tardis, plus FX/equities/
  futures/options through IB.
- **Nanosecond-resolution backtesting** on quote ticks, trade ticks, bars, order books,
  and custom data. Multi-venue + multi-strategy in one engine run.
- **Order primitives.** TIF: IOC, FOK, GTC, GTD, DAY, AT_THE_OPEN, AT_THE_CLOSE. Execution
  instructions: post-only, reduce-only, icebergs. Contingencies: OCO, OUO, OTO.
- **State persistence.** Optional Redis-backed.
- **Decimal precision mandatory** for prices and quantities (no float for money).
- **Performance claim:** engine fast enough for RL/ES agent training.
- License: LGPL-3.0; ~16k GitHub stars; commercially backed by Nautech Systems.

### AAATS (per local repo + memory)

- **Single Contabo VPS**, paper crypto, ~$200 paper floor during D.5 soak. Live-flip
  blocked by four-gap finding (2026-05-21 NO-GO) — no live trade loop exists yet.
- **Cycle-based runtime**, ~15 min per crypto cycle, cron-orchestrated. NOT event-driven.
- **Five execution strategies** (C1 stat-arb pair, C2 momentum breakout, C3 altcoin
  reversion, C5b funding-arb [halted], C6 Bollinger range) — see
  [docs/specs/strategy_catalog.md](../specs/strategy_catalog.md).
- **No live broker adapters.** Paper-mode only via `execution/paper_trader.py`
  (SQLite-backed dual-write to *_state.json files — the dual-ledger debt).
- **No backtest harness.** B.1.5 spec proposes a custom replay engine, 1–2 sessions of
  work, not yet built — [docs/decisions/2026-05-22_b15_backtest_harness.md](2026-05-22_b15_backtest_harness.md).
- **Ops + observability is the strong suit.** 10-layer monitoring (L1–L4 cron
  resilience, L5–L9 content correctness + auto-halt, L10 disk/repo watchdog). Telegram
  alerts. Doctrine-encoded kill triggers. Operator-return resumption runbook.
- **Float arithmetic** for $$ math; `paper_trades.db` schema uses `REAL` for `price` and
  `value`. Share-equality mismatch detector exists precisely because of this class of
  drift.

---

## Side-by-side capability matrix

| Capability | NT | AAATS | Gap analysis |
|---|---|---|---|
| Backtest engine | Nanosecond, multi-venue, deterministic | None — B.1.5 spec only | **Largest gap.** NT's backtester is its #1 borrow candidate. |
| Live execution loop | Production-grade, multi-venue adapters | Not built (NO-GO 2026-05-21) | Live-flip rebuild plan covers this; NT adapter PATTERN worth copying. |
| Order types | Full matrix (IOC/FOK/GTC/GTD/DAY + post-only/reduce-only/iceberg + OCO/OUO/OTO) | Skeleton (`execution/order_tif_manager.py` has 5 TIFs as enum, not wired) | Borrow the contingency set as live-flip approaches. |
| Money precision | Decimal everywhere (mandatory) | Float (`REAL` in SQLite) | **Quiet correctness bug.** Cheap to fix at ledger boundary; pays back in eliminated share-equality drift. |
| Event-driven | Yes — message bus + actors | No — cycle-based polling | Architecturally orthogonal; defer unless adding market-making. |
| Multi-venue | 13+ exchanges via adapters | Single (Binance paper) | Adapter pattern is gold; specific adapters not yet needed. |
| Order book / tick data | Native, nanosecond | Bars only (1H / 4H / 5min) | Defer — AAATS strategies are bar-based by design. |
| Risk engine | Position limits, exposure caps | 3-channel halt + L9 auto-halt + per-strategy halt + doctrine-coded kill | **AAATS wins.** NT's risk module is institutional; AAATS's is operator-aware unattended. |
| Monitoring / observability | Logging + metrics hooks (you bring Grafana/Prom) | 10-layer monitoring stack, Telegram alerts, GH Actions liveness | **AAATS wins decisively at personal scale.** |
| Operator-away resilience | Not an opinion of NT | L1–L10 + auto-cron + heartbeat watchdog + persistent halt | **AAATS wins.** This is a niche NT doesn't try to fill. |
| Capital + injection doctrine | Out of scope for NT | Encoded in doctrine + halt thresholds | **AAATS-specific; not relevant to compare.** |
| Strategy framework | `Strategy` / `Actor` class hierarchy | Plain functions + `_entry_allowed`/`_exit_allowed` gates | NT's hierarchy is more rigorous; AAATS's is more flexible. **Don't migrate.** |
| Backtest-live parity | Same code both sides (core selling point) | N/A (no backtester) | NT solves this by construction; AAATS's B.1.5 plan addresses via "import the same strategy module." |
| State persistence | Redis (optional) | JSON files + SQLite on bind mounts | AAATS's is operator-friendly; NT's is fan-out-friendly. Different goals. |
| Performance | Rust + tokio; nanosecond | Python; 15-min cycle | AAATS is not perf-bound. Don't optimize what doesn't bottleneck. |
| Documentation | Mature, public, versioned | docs/decisions + docs/known_issues + runbooks | Both strong, different audiences. |

---

## What each does well

### NautilusTrader does well

1. **Backtesting as a first-class artifact.** Nanosecond resolution, multi-venue, same
   code as live. AAATS's B.1.5 plan acknowledges this is missing; NT is a candidate
   solution, not a competitor.
2. **Adapter pattern.** Clean separation of `ExecutionClient` + `DataClient` per venue,
   normalized domain model. This is the right shape for AAATS's eventual multi-broker
   future (memory says "no OpenAlgo, direct broker adapters" — NT shows what "direct"
   looks like cleanly).
3. **Decimal-first money math.** Eliminates a class of silent correctness bugs that
   AAATS's share-equality detector exists to catch.
4. **Order-type richness.** OCO/OUO/OTO contingencies are non-trivial to retrofit; NT's
   state machine is battle-tested.
5. **Research-to-live parity by construction.** Single code path; no "the backtest used
   slightly different logic" failure mode.
6. **Performance ceiling.** Rust core + tokio means the engine can host RL training
   loops, sub-millisecond strategies, market-making. AAATS doesn't need this **now**
   but the headroom is real if the strategy stack evolves.

### AAATS does well

1. **Operating discipline at personal scale.** The L1–L10 stack catches everything from
   cron silent failures (L1) to ledger divergence (L5) to drawdown breaches (L8/L9) to
   disk/repo bloat (L10). NT has none of this — by design — you'd build it on top.
2. **Operator-away mode.** L9 persistent auto-halt + heartbeat-based GH Actions liveness
   + Telegram alerts means the bot can be left running while the operator travels. NT
   is engineered to be supervised.
3. **Cheap infrastructure.** Single Contabo VPS, no Redis/Postgres/Databento subscription,
   no Rust toolchain footprint. AAATS runs on ~$15/mo of infra; NT's full stack assumes
   data subscriptions + Redis + monitoring infra.
4. **Doctrine-encoded risk.** The $200 floor / $25 first tranche / capital-injection
   gates / 5-gate live promotion criteria — these are operator-level constraints NT
   cannot encode because NT doesn't know who's running it.
5. **Documented incident history.** `docs/known_issues/` + `docs/decisions/` provide a
   running narrative no library can match.
6. **Pair-strategy gates with niche logic** (Engle-Granger cointegration, HMM regime,
   BTC.D sentiment). NT could host the strategies; AAATS already runs them.

### Honest verdict on "which is better"

- **NT is a better engine.** If you were starting fresh and had institutional capital
  + a data subscription budget + a team to supervise it, NT is the right base.
- **AAATS is a better operated system at <$200 capital with one part-time operator.**
  NT does not try to be this.

The interesting question is not whether to replace AAATS with NT, but **which of NT's
components are cheap to port and high-leverage for the next 6 months of AAATS work.**

---

## Borrow plan — ranked by ROI

### TIER 1 — Borrow now / before live-flip

#### 1. **NT's backtest engine as the B.1.5 harness — instead of building one**
- **Why:** B.1.5 spec calls for 1–2 sessions to build a custom replay engine. NT's
  `BacktestEngine` already does this with nanosecond resolution, multi-venue,
  deterministic clock, lookahead-bias guards. The build cost is comparable; the future
  ROI is enormously higher because every future strategy gets a real harness.
- **Catch:** NT requires strategies to inherit `Strategy` class and use Decimal
  Money/Quantity types. AAATS strategies are plain functions with `_entry_allowed` /
  `_exit_allowed` gates and float math.
- **Workaround:** write thin `NTStrategyAdapter` wrappers around each AAATS strategy
  module — the wrapper consumes NT bar events, calls the existing `_entry_allowed`
  function with a synthetic context, translates Decimal back to float at the boundary.
  Wrapper layer is ~30 LOC per strategy.
- **Alternative if wrapper is too painful:** still build the AAATS-native replay
  engine per B.1.5 spec, but **steal NT's design principles**: monotonic logical
  clock, lookahead guard, fixture-based regression tests with strict tolerance.
- **Effort:** 2–3 sessions to integrate NT vs 1–2 sessions to build custom. Net cost
  ≈ +1 session for ~5x future leverage.
- **Risk:** NT pip-install adds ~80MB and a non-trivial dependency to the workstation.
  Box stays clean — backtests run only on workstation. Acceptable.
- **Recommendation:** **strong borrow** if B.1.5 hasn't started. Operator decision
  point: pay +1 session now for a real engine vs. ship custom and rebuild later.

#### 2. **Decimal precision at the ledger boundary**
- **Why:** `paper_trades.db` stores `price REAL, value REAL`. Float arithmetic is the
  root cause of the share-equality mismatch class (L5 catches the symptom). NT
  mandates Decimal for money + Quantity for size; the rule is structural, not
  test-enforced.
- **Borrow:** introduce `decimal.Decimal` at the `paper_trader.record_trade()`
  boundary; serialize to TEXT in SQLite (TEXT preserves exact representation);
  parse to Decimal on read; keep float-only inside strategy math where bar-level
  noise drowns it out.
- **Effort:** 1 session, plus a migration script.
- **ROI:** eliminates share-equality drift as a class. L5 stays as defense-in-depth.
- **Recommendation:** **borrow before live-flip.** Live capital with float money is
  malpractice; better to ship the Decimal switch during D.5 soak than during the
  live-flip rebuild sprint.

#### 3. **NT's order-type matrix — TIF + contingencies**
- **Why:** `execution/order_tif_manager.py` has the TIF enum (GTC/GTD/IOC/FOK/DAY)
  scaffolded but it isn't wired into the order lifecycle yet. NT has IOC/FOK/GTC/
  GTD/DAY/AT_THE_OPEN/AT_THE_CLOSE + post-only + reduce-only + icebergs + OCO/OUO/
  OTO contingencies. When live-flip arrives, AAATS will need at least IOC (for
  taker fills on Binance), post-only (for maker fills), reduce-only (for safe
  exit-only orders), and likely OCO (stop + take-profit bracket).
- **Borrow:** copy NT's order-side enums + flags + state-machine transitions as
  pure-Python implementations. Don't take the engine — just the spec.
- **Effort:** 1 session to enumerate + wire flags into `paper_executor.py`;
  another session per contingency type at live-flip time.
- **ROI:** unlocks bracket-order strategies; aligns paper-mode order shape with
  what the live exchange will actually accept.
- **Recommendation:** **borrow during live-flip rebuild (Track A.3 or A.4).**

#### 4. **Adapter pattern for the eventual broker abstraction**
- **Why:** Live-flip plan calls for direct broker adapters. NT's `ExecutionClient` +
  `DataClient` + `InstrumentProvider` triplet is the cleanest design in the open-
  source space — it normalizes 13+ exchanges to a single domain model and the
  strategy code doesn't change when you swap venues.
- **Borrow:** lift the **interface shape** (not the code) for AAATS's adapter
  base classes. Even if AAATS only ever connects to Binance + Zerodha, having a
  clean adapter contract means future C-tier exchanges (Bybit, OKX) drop in.
- **Effort:** 1 session at adapter-base design time (Track A.4 or A.5).
- **ROI:** prevents the "every adapter is a snowflake" path that the rebuild
  plan explicitly wants to avoid.
- **Recommendation:** **borrow at adapter-design time.** Until then, document the
  intent in the Track A plan.

### TIER 2 — Watch, consider after D.5

#### 5. **Message bus pattern (NT MessageBus)**
- **Why:** Pub/sub event bus decouples strategies from data sources. NT uses it as
  the spine of the engine. AAATS's cycle-based polling is fine at 15-min cadence but
  caps the strategy universe to bar-driven mean-reversion / breakout patterns.
  Funding-rate arb (C5b) and intra-bar gap fills would benefit from event-driven.
- **Cost:** architectural rewrite. Pre-D.5: too expensive. Post-D.5: depends on
  whether new strategies need it.
- **Recommendation:** **defer.** Re-evaluate at Track E (futures) planning.

#### 6. **Data catalog (NT Parquet-based)**
- **Why:** Standardized historical data store. NT uses Parquet with strict schemas.
  AAATS stores OHLCV in CSV and `data/historical_*/`.
- **Cost:** small migration; mostly upside if backtesting volume grows.
- **Recommendation:** **borrow if NT's BacktestEngine is borrowed (Tier 1 #1).**
  Otherwise defer.

#### 7. **Redis-backed state persistence**
- **Why:** Cross-process state sharing; survives container restarts cleanly.
- **AAATS reality:** state already persists via Docker bind mounts + JSON + SQLite,
  and the operator-return runbook is built on that. Redis adds a dependency for
  marginal gain.
- **Recommendation:** **skip.** AAATS's persistence story is already correct for
  the single-box deploy.

### TIER 3 — Do not port (AAATS already wins or NT doesn't fit)

#### 8. NT's `Strategy` / `Actor` class hierarchy
- AAATS strategies as plain functions with explicit gates work for the strategy
  universe AAATS has. Forcing them into a class hierarchy is a ~30% rewrite with
  marginal correctness gain. **Skip.**

#### 9. NT's risk engine
- AAATS's 3-channel halt + L9 persistent auto-halt + per-strategy halt is more
  operator-aware than NT's position-limit-style risk engine. Different design
  goals. **AAATS wins; don't port.**

#### 10. Rust performance core
- AAATS isn't perf-bound. Cycle takes seconds; the constraint is exchange rate
  limits, not engine throughput. **Skip.**

#### 11. NT's logging/metrics
- AAATS's `monitoring/metrics_exporter.py` + Grafana + Telegram chain is already
  the right shape and operator-tuned. **Skip.**

---

## Implementation roadmap (proposed, gated on operator approval)

### Immediate (during D.5 soak — no runtime impact)

- **This doc.** Recorded.
- **Decision point on Tier 1 #1 (NT backtest engine vs custom B.1.5).** Operator
  reads this section; decides borrow vs build before B.1.5 starts. If borrow:
  update [B.1.5 spec](2026-05-22_b15_backtest_harness.md) to reference NT.

### Pre-live-flip (Track A / B work post-D.5)

- **Decimal precision migration (Tier 1 #2).** 1 session. Add migration script.
  Update `paper_trader._conn()` schema + `record_trade` boundary.
- **Order-type matrix (Tier 1 #3).** 1 session at Track A.3 or A.4. Wire TIF +
  post-only + reduce-only into `paper_executor.py`. Defer OCO/OUO/OTO until first
  live strategy needs brackets.
- **Adapter base classes (Tier 1 #4).** 1 session at Track A.4 (live broker
  adapter design). Reference NT's `ExecutionClient` interface; AAATS Python
  implementation. Document where the abstraction lives in `execution/`.

### Post-live-flip (Track C / E)

- **Re-evaluate message bus** if strategy universe expands to intra-bar / WS-driven
  patterns (e.g., futures funding skew, market-making).
- **Re-evaluate data catalog** if backtest volume grows past current file-based
  storage.

---

## Risks of borrowing too much

1. **NT is a 100k-LOC dependency.** Pulling it in for the backtest engine costs a
   non-trivial install footprint on the workstation. Acceptable; box stays clean.
2. **NT API changes** (currently in Cython → PyO3 migration). Version-pin in
   `requirements-dev.txt`; revisit on minor-version bumps only.
3. **License: LGPL-3.0.** Compatible with AAATS's private use; not a blocker. If
   AAATS ever open-sources, LGPL-3.0 dependency is fine for hosted use, restrictive
   for distribution. Personal use: irrelevant.
4. **Overfitting the system to NT semantics.** If you borrow NT's Strategy class,
   you're locked into its event model. **The Tier 1 borrows above are all interface
   borrows or vendored libraries** — no architectural lock-in.

---

## Open questions for operator

1. **B.1.5: borrow NT or build custom?** Tier 1 #1 above. Recommended: borrow.
2. **Decimal migration during D.5 soak — acceptable mid-soak change?** Recommended:
   yes, behind a feature flag with `paper_trades.db` schema migration; rolled out
   on a quiet operator-present window.
3. **Adapter base classes — wait for Track A.4 or sketch now?** Recommended: sketch
   the interface now (~½ session) so live-flip rebuild plan has the shape locked
   in. No code change to runtime.

---

## References

- NautilusTrader README: https://github.com/nautechsystems/nautilus_trader
- NautilusTrader docs: https://nautilustrader.io/docs/
- AAATS strategy catalog: [docs/specs/strategy_catalog.md](../specs/strategy_catalog.md)
- AAATS B.1.5 backtest harness spec: [2026-05-22_b15_backtest_harness.md](2026-05-22_b15_backtest_harness.md)
- AAATS live-flip rebuild plan: [2026-05-22_live_flip_rebuild_plan.md](2026-05-22_live_flip_rebuild_plan.md)
- AAATS ledger Q1–Q4 recommendations: [2026-05-21_ledger_spec_recommendations.md](2026-05-21_ledger_spec_recommendations.md)
- AAATS repo analysis (2026-05-10, prior framing): memory `aaats_repo_analysis_decisions.md` — "no OpenAlgo, direct broker adapters, fork 8 tradermonty skills." NT's adapter pattern is the cleaner reference for the "direct broker adapters" path.
