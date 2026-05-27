# B.1.5 backtest harness — design + phase plan (2026-05-27)

**Status:** Gap-analysis design (Phase 1 deliverable).
**Inventory:** [docs/specs/b15_data_inventory.md](b15_data_inventory.md).
**Original spec (session 9, pre-C3-shipment):** [docs/decisions/2026-05-22_b15_backtest_harness.md](../decisions/2026-05-22_b15_backtest_harness.md).

This memo treats the partly-shipped C3 implementation as the baseline and answers the five subsections requested for B.1.5 Phase 1.

---

## a. Goals — GO/NO-GO outputs

The harness exists to gate two operator decisions:

1. **Reset gate** — should we reset the paper book to $200 and start a 30d soak? Per [doctrine amendment line 84](../decisions/2026-05-23_doctrine_amendment_200_floor.md#L84): "The B.1.5 backtest stress-test (added 2026-05-23) is the gate that decides whether the strategy stack is worth running 30 days on."
2. **Live-flip gate** (B.3 → C track) — combined with B.3 4-week soak result, B.1.5 supports the "final equity ≥ $200" criterion check on out-of-sample historical data.

### Numeric floors

Pulled from doctrine + session-9 thresholds:

| Floor | Source | Value |
|---|---|---|
| Sharpe (paper success) | [locked_doctrine §"Paper success criteria":34](../operator/aaats_locked_doctrine_2026_05_14.md#L34) | trailing 30d Sharpe **> 0** |
| Max drawdown ceiling | [locked_doctrine §"Paper success criteria":35](../operator/aaats_locked_doctrine_2026_05_14.md#L35) | **< 15%** |
| Closed trades floor | [locked_doctrine §"Paper success criteria":33](../operator/aaats_locked_doctrine_2026_05_14.md#L33) | **≥ 30** |
| Live-scale Sharpe | [locked_doctrine §"Phase 1 exit gates":45](../operator/aaats_locked_doctrine_2026_05_14.md#L45) | trailing 90d Sharpe **> 0.8** |
| Live-kill triggers | [locked_doctrine §"Kill triggers":66](../operator/aaats_locked_doctrine_2026_05_14.md#L66) | DD > 25%, or Sharpe < 0 on 90d |

### Recommendation rule (session-9, codified in run_b15_c3.py:53-73)

```
GO      = pnl_usd > 0
          AND sharpe > 0.5
          AND profitable_regime_count >= 2
          AND slippage_sensitivity_50bps_pnl_usd > 0
PARTIAL = pnl_usd > 0 but fails any other criterion
NO-GO   = pnl_usd <= 0 OR harness failed to complete
```

Implementation [tools/backtest/run_b15_c3.py:53-73](../../tools/backtest/run_b15_c3.py#L53-L73). Note `sharpe > 0.5` is *stricter* than locked-doctrine's "> 0" — session-9 chose a higher harness bar than the live-soak bar, on the theory that backtest is permissive (no HMM/BTC.D gates) and should clear a higher hurdle to compensate. Reasonable; codified.

### Output schema (already produced by run_b15_c3.py)

`data/backtest_results/c3_60d_summary.json`:
```
{
  "as_of": ISO8601,
  "horizon_days": int,
  "trades": int,
  "pnl_usd": float,
  "sharpe": float,
  "win_rate": float,
  "profitable_regime_count": int,
  "slippage_sensitivity_50bps_pnl_usd": float,
  "recommendation": "GO" | "PARTIAL" | "NO-GO",
  "evidence": str,
  "_metadata": {…universe, regime_results, headline_metrics, slip_50bps_metrics…}
}
```

Missing from the schema vs locked-doctrine criteria: explicit `max_drawdown_pct` field at the top level (it exists in `headline_metrics` nested dict but not surfaced as a verdict gate). Phase 2 add.

---

## b. Data requirements

**Have**: 60d × 1H bars for {BTC, SOL, LINK, AVAX, DOT} USDT pairs. 1,440 bars/symbol.

**Need for full strategy coverage**:

| Strategy | Required symbols | Required depth | Status |
|---|---|---|---|
| C1 stat_arb (BTC/ETH pair) | BTC, ETH | ≥ 14 days for corr14d window, prefer 60d+ | **ETH missing** |
| C3 altcoin_reversion | BTC + 4-symbol universe | ≥ LOOKBACK_BARS+50 ≈ 16 days, prefer 60d | ✓ |
| C5b funding_arb | Perpetual funding rate history (Binance USDM-Futures `fundingRate` endpoint, not klines) | ≥ 30d | **Not modeled in fetcher** |
| C6 bollinger_range | BTC, ETH, SOL | ≥ 20 + 14 bars for BB(20) + RSI(14), prefer 60d | **ETH missing** |
| C2 momentum | BTC + universe | ≥ 4h × 20 bars for breakout window | TBD |

**Definition of "≥2 full bear/bull cycles"** for confident regime coverage: BTC realized 30d vol oscillation through high and low quartiles ≥ 2 round trips. Empirically that's ~6 months for crypto. Out-of-scope here; queued as Phase 4.

**Single-fetch plan to close data gap for C1+C6+C3:**
```
for sym in ("ETH/USDT",):
    fetch_ohlcv(sym, timeframe="1h", days_back=60, end_ts=2026-05-23T11Z)
```
1 symbol × 60d × 1h = 1,440 bars = single ccxt batch. < 5s, no rebuild.

---

## c. Architecture — choice already locked

The session-9 prompt's three architectural candidates are now historical:

| Candidate | Reality |
|---|---|
| i. Vectorized replay (numpy/pandas over OHLCV) | Considered & rejected — re-implementing strategy logic outside `trading/` was the original sin the session-9 spec ([2026-05-22_b15_backtest_harness.md:30](../decisions/2026-05-22_b15_backtest_harness.md#L30)) calls "the bug source." |
| ii. Strategy-driver replay (call run_crypto with synthetic clock) | Considered & rejected — would require wall-clock injection into every strategy file (144 direct `datetime.now()` calls per the inventory agent), high refactor cost, slow. |
| **iii. Hybrid** (pure-helpers reused, driver reimplemented) | **CHOSEN.** Implemented in [tools/backtest/c3_replay.py](../../tools/backtest/c3_replay.py). c3_replay imports C3's `_compute_z_score`, `_rsi`, `_realized_daily_vol`, `_compute_trade_size` directly ([c3_replay.py:40-43](../../tools/backtest/c3_replay.py#L40-L43)); reimplements only the entry/exit driver loop. |

**Failure-injection (per [feedback_adversarial_vs_verification_testing.md] in memory):** the hybrid architecture lets us inject failures at the driver level (force a SELL trigger to occur mid-loop, simulate a crash between strategy decision and ledger write) without polluting strategy code. Phase 3 will codify adversarial bar fixtures. Today's harness is *verification-only* — it only confirms the strategy produces expected numbers on benign data.

**Architectural debt the existing C3 implementation accumulated** (carry-forward):

1. Replay is **permissive** vs production — disables HMM BEAR-regime gate ([c3_replay.py limitations](../../tools/backtest/c3_replay.py)) and BTC.D fast-rise filter. Recommendation is an upper bound; live underperforms. Phase 3 should evaluate whether to fold these gates back in (would require historical HMM state, which doesn't exist).
2. Spread + exchange fees set to 0 in base run. Only 50bps slippage sensitivity is tested. Phase 4 wants a granularity sweep (10/25/50/75/100 bps).
3. No live-trade parity test (the session-9 spec's "10-trade fixture ±2¢" exit criterion). Phase 3 deliverable.
4. Per-trade Sharpe annualization uses `sqrt(60)` — internally consistent and documented at [c3_replay.py:252-257](../../tools/backtest/c3_replay.py#L252-L257), but distinct from the doctrine criterion's "trailing 30d Sharpe" which implies a time-series Sharpe, not per-trade. Operator should be aware these are different metrics computed against different data shapes.

---

## d. Phase plan

Numbered, sized in sessions:

### Phase 2 — Step 1: fix `sqrt(252)` in live metrics (~½ session)

Two callsites:
- [monitoring/metrics_exporter.py:851](../../monitoring/metrics_exporter.py#L851) — replace `* math.sqrt(252)` with `* math.sqrt(len(pnls) / 14.0 * 365.0)` (14 = window days in the SQL `cutoff_14d` filter).
- [analytics/strategy_optimizer.py:125](../../analytics/strategy_optimizer.py#L125) — extend SELECT to pull `timestamp`, compute window from min/max, annualize `* sqrt(len(pnls) / window_days * 365)`.

Deploy impact: live Grafana panel `aaats_rolling_sharpe_14d` will jump to the corrected value next scrape after rebuild of `aaats-metrics`. The corrected value will be *smaller in magnitude* than today's (because actual trade rate is ~5/month not 252/year). Operator should accept this once and recalibrate any panel thresholds.

Container rebuild required: `aaats-metrics` only. No strategy/risk code touched. Bind-mount-friendly? `monitoring/` is baked into image (per CLAUDE.md deploy machinery), so rebuild needed.

### Phase 2 — Step 2: fetch ETH/USDT bars + extend C6/C1 (~½ session)

```
venv\Scripts\python -c "from tools.backtest.historical_data import fetch_ohlcv; fetch_ohlcv('ETH/USDT', '1h', days_back=60, end_ts='2026-05-23T11:00Z')"
```
Outcome: `data/historical/ETH_USDT_1h.parquet` joins the cache. Unblocks C1 and C6 replay design.

### Phase 3 — C1 stat_arb replay (~1 session)

Mirror the c3_replay pattern for `trading/stat_arb.py`:
- Extract pure helpers (`_compute_zs`, `_z_entry_allowed`, `_z_exit_allowed`) into a clear pure-function block in stat_arb.py (small refactor inside trading/, deliberately small scope — adds NO behavior change to live).
- Write `tools/backtest/c1_replay.py` analogous to c3_replay.
- Extend run_b15_c3.py → `run_b15_c1.py` (or generalize, see Phase 4).
- Single contract test in tests/test_b15_backtest_harness.py.
- Run against ETH+BTC cache; record verdict.

### Phase 3 — C6 = bollinger_range replay (~1 session)

Same pattern as C1. `trading/bollinger_range.py` already has clean per-symbol entry/exit logic ([bollinger_range.py:228](../../trading/bollinger_range.py#L228)). Pure-helper extraction is straightforward.

### Phase 3 — Live-trade parity test (~½ session)

The session-9 spec's "10-trade fixture ±2¢" exit criterion. Take 10 closed C3 trades from `runtime/paper_trades.db`, feed the same OHLCV slice to `replay_c3`, assert per-trade `pnl_usd` matches within $0.02. This is the regression test that catches future divergence between replay and live.

### Phase 4 — Multi-strategy aggregation + regime depth (~1-2 sessions)

- Generalize `run_b15_c3.py` to `run_b15_aggregate.py` that produces a portfolio-level summary across {C1, C3, C6, C5b}.
- Extend historical depth from 60d → 6 months (or longer) via paginated ccxt fetch. ~30 min compute, single overnight run.
- Granularity sweep across slippage_bps ∈ {0, 10, 25, 50, 75, 100} for sensitivity.
- Surface `max_drawdown_pct` at top of summary JSON (not just nested in `headline_metrics`).
- Optional: C5b funding-rate ingest (separate Binance endpoint — `fapi/v1/fundingRate`).
- Optional: C2 momentum if doctrine carves out (currently doctrine-categorized "LIKELY NEVER").

**Total budget**: ~4 sessions to close Phase 2-4, modest. Phase 1 (this session) was design+verification. Phase 2 is mechanical (sqrt fix + ETH fetch). Phase 3 is the bulk (3 sub-sessions × ½–1 session). Phase 4 is the multi-strategy assembly.

---

## e. Non-goals

Out of B.1.5 scope (deferred to other tracks):

- **Live paper-trading parity at runtime cycle level.** The harness validates strategy LOGIC against historical data. It does NOT replicate the live runner's full lifecycle (kill-switch state, halt files, autopush, monitoring layers L1-L11). Track D owns runtime parity.
- **Multi-broker / multi-venue replay.** Single-exchange (Binance public REST) only. Multi-venue replay is a Track E concern, post-live-flip.
- **Futures / perpetual leverage replay.** Spot 1× only. C5b funding-arb perpetual leg is the one exception — its design phase will need a perpetual-aware fill model.
- **Strategy-design exploration.** Operator chooses params; harness executes sweeps. No agent-driven param search.
- **Live-flip authorization.** B.1.5 outputs feed B.1 (triage) and inform B.3 expectations. They never directly unlock G1-G5 tranche gates — only operator decides.
- **Re-evaluation of locked doctrine.** If the doctrine numeric floors look wrong against B.1.5 data, that's a doctrine-amendment discussion (like the 2026-05-23 $200 amendment), not a harness change.

---

---

## Known model gap: live C3 path applies zero slippage

Added 2026-05-27 during Phase 2 deploy. The harness and the live strategy code use **different slippage models** today; live = zero, harness = configurable. Surfaced here so future sessions don't conflate harness PnL with live (soak) PnL.

### What live C3 does

The C3 live runner at [trading/altcoin_reversion.py](../../trading/altcoin_reversion.py) computes capital directly from raw bar-close prices:

- **EXIT** ([altcoin_reversion.py:653](../../trading/altcoin_reversion.py#L653)): `capital += size + pnl` — capital returns plus computed PnL, where `pnl` is derived from raw close prices, no slippage subtraction.
- **ENTRY** ([altcoin_reversion.py:754](../../trading/altcoin_reversion.py#L754)): `capital -= trade_usd` — full notional deducted, no slippage charge.

The runner-level `_fill_price` helper at [live_paper_runner.py:1055-1083](../../trading/live_paper_runner.py#L1055-L1083) DOES model dynamic slippage (0.10–0.40% based on realized vol), but C3 doesn't route through it — C3's per-cycle code path computes its own capital math independently.

### What the C3 harness does

[tools/backtest/c3_replay.py:127,200](../../tools/backtest/c3_replay.py#L127) applies a configurable `slippage_bps` symmetrically (entry pays +slip, exit pays -slip). The Phase 1 run on 60d cached data:

| Slippage | PnL ($100 cap) | Sharpe | Win rate | Recommendation |
|---|---|---|---|---|
| 0 bps (headline) | **+$5.43** | +1.52 | 47.7% | PARTIAL (passes pnl/sharpe/regimes, fails slip-sensitivity gate) |
| 50 bps | **-$5.72** | -2.08 | 31.6% | (PARTIAL because pnl<0 in this sensitivity branch) |

50bps is a realistic round-trip cost for Binance USDT spot at small notional (taker fee 10bps + spread 5–25bps round-trip). The strategy's headline P&L hides this fragility.

### Consequences

1. **Soak C3 PnL is biased optimistic.** Real-world live-flip fills will eat 5–20bps round-trip. The +$0.99 realized PnL on the running soak (per `runtime/paper_portfolio.json`) reflects zero-slippage accounting; live-money equivalent would be lower (perhaps net-negative for some windows).
2. **Don't compare harness PnL to live PnL directly.** They measure different things. The harness's **slippage-sensitivity output** IS the live-flip risk model — not the headline-PnL number.
3. **GO/NO-GO must read the slippage row.** The session-9 recommendation rule already requires `slippage_sensitivity_50bps_pnl_usd > 0` for a GO verdict ([run_b15_c3.py:53-73](../../tools/backtest/run_b15_c3.py#L53-L73)). Today's verdict (PARTIAL) is the correct one — the strategy is not yet live-flip ready under realistic slippage assumptions.

### Resolution paths (out of B.1.5 scope — future sprint)

Two options for closing the model gap:

(a) **Make C3 live path apply slippage.** Modify `trading/altcoin_reversion.py` to call `live_paper_runner._fill_price` (or an equivalent helper) on entry + exit, so the live capital math mirrors the harness math. Pro: single source of truth. Con: changes live behavior mid-soak; would invalidate the current 30d baseline.

(b) **Document a paper→live haircut factor at the GO/NO-GO threshold.** Leave live C3 as-is; teach the doctrine criterion to apply a haircut (e.g. "live-flip GO if harness 50bps PnL > 0 AND paper-soak PnL > harness 50bps PnL + N%"). Pro: no live-code change mid-soak. Con: adds doctrine complexity, harder to audit.

Operator decision; queue for post-D.5-soak triage.

### Cross-references

- [aaats_c3_slippage_fragility.md] in memory — concise anchor for live-flip readiness reviews.
- [tools/backtest/c3_replay.py:127](../../tools/backtest/c3_replay.py#L127) — entry slippage application
- [tools/backtest/c3_replay.py:200](../../tools/backtest/c3_replay.py#L200) — exit slippage application

---

---

## C6 Sharpe sanity check (Phase 3)

Added 2026-05-27 during Phase 3. The post-sqrt-fix live `aaats_rolling_sharpe_14d` panel reads ≈8.4 for C6 (`bollinger_range`), which would be exceptional if real. Built a minimal harness ([tools/backtest/c6_replay.py](../../tools/backtest/c6_replay.py)) and ran 60d corroboration to confirm vs. dismiss.

### Setup

- Universe: BTC/USDT, ETH/USDT, SOL/USDT (matches `bollinger_range.SYMBOLS`).
- Cache: `data/historical/{BTC,ETH,SOL}_USDT_1h.parquet`, window 2026-03-24T11Z → 2026-05-23T10Z, 1440 bars × 3 symbols.
- Strategy parameters snapshot at trading/bollinger_range constants (BB(20,2), RSI(14), %B entry < 0.15, RSI entry < 32, target %B ≥ 0.50, TP +1.5%, stop -1.0%, time-stop 12h, CAPITAL_PCT 6%, MAX_CONCURRENT 2).
- Two simplifications vs. live, both PERMISSIVE (make replay look better than live should):
  - **Regime gate skipped** in permissive run (live requires HMM-RANGE_BOUND).
  - **Regime-flip exit skipped** (live exits on flip to BULL/BEAR).
- Regime-gated run uses a BTC BBand-width <50th-percentile proxy (narrow bands ≈ RANGE_BOUND) as a transparent stand-in for the HMM.

### Results

| Run | Trades | PnL ($100 cap) | Sharpe | Win rate | Profit factor | Max DD |
|---|---|---|---|---|---|---|
| Permissive, 0 slip | 85 | **-$0.87** | -1.28 | 49.4% | 0.67 | 0.9% |
| Permissive, 50bps | 105 | -$6.59 | -9.80 | 12.4% | 0.04 | 6.6% |
| Regime-gated, 0 slip | 44 | -$0.64 | -1.82 | 43.2% | 0.58 | 0.7% |
| Regime-gated, 50bps | 55 | -$3.61 | -10.09 | 14.5% | 0.05 | 3.6% |

### Verdict — (c) per Phase-3 prompt taxonomy: <2 or negative

**C6 has no demonstrated edge on this 60d window.** Sharpe is negative even at zero friction, in both permissive (no regime gate) and regime-gated configurations. Regime gating actually made Sharpe *worse* (-1.28 → -1.82) — the trades filtered out were marginally net-positive, suggesting the strategy's signal degrades under stricter conditions rather than improving.

The gap to the live 14d Sharpe of +8.41 is **9.7 units**. Neither regime gating nor slippage modeling can explain that. The most defensible interpretation: the live 14d reading is a small-sample artifact (window may contain only 2–4 closed C6 trades, favorable bar alignment, or coincident pickup of a single strong move).

### Recommendation — downweight live 14d Sharpe in any forward decision

Per the Phase-3 prompt's explicit warning for verdict (c): **do not treat the live 14d aaats_rolling_sharpe_14d for C6 as a real edge.** When evaluating C6 for any forward decision (live-flip readiness, capital allocation, parameter changes), use the 60d harness number (Sharpe -1.28 permissive / -1.82 gated), not the rolling 14d panel.

### What this does NOT do

Per the prompt: **NOT changing live thresholds based on this finding alone.** The doctrine bakes in strategy-level decisions in Phase 4 when all strategies have 60d verdicts. Live C6 continues to run during the soak; the operator decides post-D.5 whether to keep, retune, or retire it.

### Caveats specific to this corroboration

1. **Single 60d window.** A different window might produce a different Sharpe. The fact that one window shows negative is not "C6 is permanently dead"; it is "C6 has no robust edge in this window."
2. **BBand-width proxy is approximate.** The live HMM regime classifier uses additional signals (returns autocorrelation, dispersion). The proxy is a first-order stand-in.
3. **Spread + fees set to 0 in base run.** Same caveat as C3 / C1 — real-world Binance fills will eat additional bps.
4. **Statsmodels not installed on workstation** — affects C1 cointegration check only (forced p=0.0). C6 has no cointegration dependency.

---

## Cross-references

- Inventory: [docs/specs/b15_data_inventory.md](b15_data_inventory.md)
- Original session-9 spec: [docs/decisions/2026-05-22_b15_backtest_harness.md](../decisions/2026-05-22_b15_backtest_harness.md)
- Locked doctrine: [docs/operator/aaats_locked_doctrine_2026_05_14.md](../operator/aaats_locked_doctrine_2026_05_14.md)
- Doctrine amendment: [docs/decisions/2026-05-23_doctrine_amendment_200_floor.md](../decisions/2026-05-23_doctrine_amendment_200_floor.md)
- C1 replay: [tools/backtest/c1_replay.py](../../tools/backtest/c1_replay.py)
- C3 replay: [tools/backtest/c3_replay.py](../../tools/backtest/c3_replay.py)
- C3 runner: [tools/backtest/run_b15_c3.py](../../tools/backtest/run_b15_c3.py)
- C6 replay: [tools/backtest/c6_replay.py](../../tools/backtest/c6_replay.py)
- Backtest engine: [backtesting/engine.py](../../backtesting/engine.py)
