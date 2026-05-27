# Phase B.1.6 — C3 → NautilusTrader port + the graduation gate

**Status:** PROPOSED — planning only, no runtime impact. Workstation-only research track; the Contabo box is untouched.
**Authored:** 2026-05-27 (Cowork session, D.5 soak day 4).
**Premise:** "Combine NT + AAATS" means *connect them at one clean handoff*, not merge codebases. NT becomes the research/validation brain; AAATS stays the deployment/survival body. This doc specifies the first concrete instance of that pipeline: re-validate C3 — your only non-dead strategy — inside NautilusTrader's honest fee/fill model, and define the **graduation gate** that any strategy must clear before it earns live capital.
**Supersedes nothing.** Extends Track B after [`2026-05-22_b15_backtest_harness.md`](2026-05-22_b15_backtest_harness.md) (B.1.5, now shipped) and feeds [`2026-05-22_live_flip_rebuild_plan.md`](2026-05-22_live_flip_rebuild_plan.md) Track C.

---

## Why this phase exists

B.1.5's break-even sweep (2026-05-27) returned three verdicts: C1 **DEAD** (BE 2.83 bps/side), C6 **DEAD** (unprofitable at zero cost), C3 **MARGINAL** (BE 22.79 bps/side — survives Binance spot taker at 10bps with a ~12bps buffer for market impact). C3 is the only strategy worth more cycles.

But the B.1.5 verdict carries three caveats that block a live-flip GO, all of which are exactly what NautilusTrader is built to remove:

1. **Single 60-day window, no out-of-sample.** `tools/backtest/c3_replay.py` ran on the only cached history. C3's 22.79 bps break-even could be an artifact of one favourable 60d regime.
2. **Naive execution model.** `c3_replay.py` applies a *symmetric* `slippage_bps` to a bar-close fill and **no fees at all** ([c3_replay.py:126-128](../../tools/backtest/c3_replay.py#L126-L128)). Real C3 entries are spot alt longs that pay a 10bps taker fee + 2-15bps market impact. The naive model cannot distinguish "C3 survives with limit/maker execution" from "C3 dies to taker fills" — and that distinction *is* the live-viability question.
3. **Float math.** Both `c3_replay.py` and the live `paper_trader` use float for price/size. At C3's ~12bps margin of safety, rounding leakage is not negligible.

NautilusTrader fixes all three by construction: 6-month (or longer) multi-symbol backtests, a real `MakerTakerFeeModel` + `FillModel` that separates maker/taker fills and models slippage against quotes/bars, and mandatory `Decimal` money. **Porting C3 into NT is the cheapest way to turn "MARGINAL on one window with a toy cost model" into "GO / NO-GO on 6 months with a realistic one."**

This is also the pilot for the combine-both pipeline: if C3 graduates cleanly through NT, we have both a live-viable edge *and* a proven research→deploy handoff we reuse for every future strategy.

---

## What we are NOT doing

- **Not** running NT as a separate live bot. NT lives on the workstation as a research tool. The box keeps running AAATS.
- **Not** porting C1 or C6. Your own data says they are dead at any cost level — porting them is wasted effort.
- **Not** rewriting C3's strategy logic. We reuse C3's pure functions verbatim (the same ones `c3_replay.py` already imports). NT only replaces the *driver* and the *cost model*.
- **Not** committing to NT's `Strategy` class for production. This is a validation harness. Production deployment stays in the AAATS runtime unless/until a later decision says otherwise.

---

## Architecture — the combine-both pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  RESEARCH BRAIN (NautilusTrader, workstation only)                │
│                                                                   │
│   6mo Binance OHLCV ──► NT BacktestEngine ──► realistic fills     │
│   (historical_data.py)   + MakerTakerFeeModel  + Decimal money    │
│         │                       │                                 │
│         │                 C3NautilusStrategy (wraps C3 pure fns)   │
│         │                       │                                 │
│         ▼                       ▼                                 │
│   in-sample / OOS split   net-of-cost PnL, Sharpe, DD, PF         │
│                                 │                                 │
│                                 ▼                                 │
│                        ┌─────────────────┐                        │
│                        │ GRADUATION GATE │  (objective criteria)  │
│                        └─────────────────┘                        │
│                                 │ PASS                            │
└─────────────────────────────────┼─────────────────────────────────┘
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  DEPLOYMENT BODY (AAATS, Contabo box)                             │
│   Graduated strategy runs in the existing run_crypto cycle,       │
│   inheriting L1–L10 monitoring, halt channels, operator-away mode │
└─────────────────────────────────────────────────────────────────┘
```

The handoff is a single artifact: a **graduation report** (`data/graduation/<strategy>_<date>.json`) that the gate emits on PASS. Nothing deploys without one.

---

## Scope — files touched (all workstation-only, new `tools/nautilus/` tree)

| File | Purpose |
|---|---|
| `tools/nautilus/__init__.py` | New package. |
| `tools/nautilus/c3_strategy.py` | `C3NautilusStrategy(Strategy)` — NT strategy that buffers bars per symbol and delegates the signal to `c3._compute_z_score` / `c3._should_exit` logic. **Imports C3's pure functions; reimplements only the driver.** |
| `tools/nautilus/data_loader.py` | Convert the 6mo OHLCV DataFrames (from existing `tools/backtest/historical_data.py`) into NT `Bar` objects via `BarDataWrangler`. Defines the spot instruments (SOL/USDT, LINK/USDT, AVAX/USDT, DOT/USDT, BTC/USDT, ETH/USDT). |
| `tools/nautilus/run_c3_oos.py` | Driver: build `BacktestEngine`, register a `SIM` venue with `MakerTakerFeeModel` (Binance VIP-0 tiers) + `FillModel`, load in-sample + OOS windows, run, dump metrics. |
| `tools/graduation/gate.py` | Pure function: takes a metrics dict + the gate thresholds, returns PASS/FAIL + reasons. Emits the graduation report JSON. |
| `tests/test_c3_nautilus_parity.py` | Assert the NT port reproduces `c3_replay.py` PnL within tolerance **when NT fees are set to zero and slippage symmetric** — proves the port didn't change the strategy, only the cost model. |
| `docs/specs/graduation_gate.md` | Canonical spec for the gate criteria (so future strategies use the same bar). |

Extended (not rewritten):
- `tools/backtest/historical_data.py` — add a 6-month fetch window (the B.1.5 caveat: "no OOS without 6mo fetch"). Binance public klines REST, no auth, free.

---

## C3 strategy adapter — the key design point

C3's pure functions are already cleanly isolated (`c3_replay.py` proves this — it imports `_compute_z_score`, `_rsi`, `_realized_daily_vol`, `_compute_trade_size` directly). The NT adapter does the same, so **strategy logic stays identical and the validation stays honest**:

```python
# tools/nautilus/c3_strategy.py  (sketch — not final code)
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.data import Bar
from nautilus_trader.model.orders import LimitOrder      # post-only path
from decimal import Decimal
import pandas as pd
from trading import altcoin_reversion as c3

class C3NautilusStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self._closes: dict[str, list[float]] = {}   # symbol -> rolling closes
        self._positions_meta: dict[str, dict] = {}   # symbol -> {entry_idx, max_z, ...}

    def on_bar(self, bar: Bar) -> None:
        sym = bar.bar_type.instrument_id.symbol.value
        self._closes.setdefault(sym, []).append(float(bar.close))
        # Reuse C3's EXACT z-score + exit logic on the buffered closes.
        # BTC buffer is maintained the same way; build the two DataFrames
        # c3._compute_z_score expects and call it verbatim. Entry threshold
        # Z_ENTRY, trailing exit, hard stop, time stop, denylist, cooldown,
        # vol-adjusted sizing — all from the c3 module, no reimplementation.
        ...
        # DIFFERENCE FROM PAPER-MODE: submit a post-only LIMIT order at the
        # bar close (maker path) instead of an implicit market fill. This is
        # the "clean execution" the B.1.5 memo says C3 needs. NT's fill model
        # decides whether the limit fills; unfilled entries are simply skipped,
        # exactly as a real maker order would behave.
```

The single behavioural change from paper-mode is **maker/limit execution instead of naive market fills** — which is the entire live-viability hypothesis for C3. NT lets us A/B this: run once with market orders (taker, 10bps) and once with post-only limits, and measure whether C3's 12bps buffer survives.

---

## Data — 6-month out-of-sample

- **Source:** Binance public `klines` REST (free, no auth), via the existing `tools/backtest/historical_data.py` fetch+cache, window extended to 180 days.
- **Symbols:** BTC/USDT, ETH/USDT (reference legs) + SOL/USDT, LINK/USDT, AVAX/USDT, DOT/USDT (C3 universe). Denylisted symbols (OP/ARB/PUMP/FET/LUNC) stay excluded — they're entry-blocked in production anyway.
- **Resolution:** 1H bars (matches C3 production resolution; do not change).
- **Split:** first 4 months = in-sample (sanity check the port + cost model), last 2 months = **out-of-sample** (the number that counts). Optionally a rolling walk-forward if the 2mo OOS is too thin for significance.

---

## Fee + fill model — the honest cost layer

Configure NT's `SIM` venue with Binance VIP-0 economics (from the B.1.5 memo's reference table):

| Path | Fee (per side) | Modeled via |
|---|---|---|
| Spot taker (market order) | 10 bps | `MakerTakerFeeModel`, taker leg |
| Spot maker (post-only limit) | 10 bps | `MakerTakerFeeModel`, maker leg |
| Market impact | 2–15 bps (size/depth dependent) | `FillModel` slippage / probabilistic fill |

Note: at VIP-0 Binance spot maker and taker are **both 10bps** — so C3's execution edge is NOT a fee discount; it's **avoiding the 2-15bps market impact** by resting a limit order instead of crossing the spread. NT's `FillModel` is what lets us measure that. This is the precise mechanism the B.1.5 memo flagged ("switching from naive market orders to TWAP/limit execution could preserve the edge") and it cannot be tested in `c3_replay.py`.

---

## The graduation gate (canonical criteria)

A strategy graduates from NT research to AAATS live deployment **only** if it clears every criterion below on the **out-of-sample** window. These become `docs/specs/graduation_gate.md` and apply to all future strategies, not just C3.

| # | Criterion | Threshold | Rationale |
|---|---|---|---|
| G1 | Net PnL after realistic fees + impact | > 0 on OOS | The floor. A strategy that loses money net of cost is not an edge. |
| G2 | Sharpe (per-trade, annualized) | ≥ 1.0 on OOS | Below this, the edge is indistinguishable from noise at this trade count. |
| G3 | Max drawdown | ≤ 20% on OOS | Aligns with the L9 persistent-halt threshold — don't deploy something that would trip its own kill switch. |
| G4 | Trade count | ≥ 30 closed trades on OOS | Statistical significance floor. Fewer = small-sample artifact (the exact trap C6's +8.41 live Sharpe fell into). |
| G5 | Profit factor | ≥ 1.3 on OOS | Gross wins / gross losses. Below 1.3 is too fragile to survive regime shift. |
| G6 | In-sample / OOS degradation | OOS Sharpe ≥ 0.5 × in-sample Sharpe | Catches overfit: if OOS performance collapses vs in-sample, the params are curve-fit. |
| G7 | Maker-fill dependency check | Edge survives if X% of limit orders go unfilled | If C3 only works assuming 100% maker fills, it's fragile. Stress at 50% fill rate. |

PASS on all 7 → emit `data/graduation/c3_<date>.json` → C3 is cleared for the live-flip Track C decision. FAIL on any → C3 stays paper-only and the failed criterion tells you exactly what to fix.

**C3's expected outcome:** honest. Its OOS break-even is right at the cost line, so G1/G2 are live coin-flips. That's the point — better to learn it in NT now than after flipping $25 of real capital into it.

---

## Exit criteria for B.1.6

- `tests/test_c3_nautilus_parity.py` passes: NT port with zero-fee + symmetric-slip reproduces `c3_replay.py` PnL within ±2¢ per trade (proves logic identity).
- `run_c3_oos.py` produces a metrics dict with all G1–G7 fields on the 6mo data.
- `gate.py` emits a graduation report (PASS or FAIL) for C3.
- `docs/specs/graduation_gate.md` written and referenced from CLAUDE.md's doc-layout section.

---

## Estimate + sequencing

| Step | Work | Sessions |
|---|---|---|
| 1 | Extend `historical_data.py` to 6mo + fetch the 6 symbols | 0.5 |
| 2 | `data_loader.py` (DataFrame → NT Bars + instrument defs) | 0.5 |
| 3 | `c3_strategy.py` adapter + parity test | 1.5 |
| 4 | `run_c3_oos.py` + fee/fill model config | 1 |
| 5 | `gate.py` + `graduation_gate.md` + run C3 through it | 0.5 |

~4 sessions, Sonnet-grade (it's implementation of a decided design; escalate to Opus only if the NT fill-model config turns non-obvious). Sub-task friendly — steps 1-2 unblock 3, step 5 is the payoff.

---

## Risks

1. **NT install footprint on the workstation** (~80MB + PyO3 wheels). Acceptable; isolated in a venv, box untouched. Version-pin in `requirements-dev.txt`.
2. **NT API churn** (mid Cython→PyO3 migration). Pin to a `latest` release tag, not nightly. Re-test on minor bumps only.
3. **Bar-only data can't fully model intra-bar limit fills.** NT's `FillModel` approximates fill probability from bar OHLC; it's better than `c3_replay.py`'s bar-close assumption but not tick-perfect. Document the assumption; treat G7 (maker-fill dependency) as the stress that bounds this uncertainty.
4. **C3 fails the gate.** This is a *successful* outcome, not a failure of the phase — it means you avoided flipping capital into a marginal edge, and the pipeline is proven for the next strategy. The combine-both thesis doesn't depend on C3 specifically graduating; it depends on the gate being real.
5. **Scope creep into "port everything to NT."** Explicitly out of scope. B.1.6 is C3-only. Generalizing the adapter to other strategies is a *later* decision gated on C3 proving the pattern.

---

## Open questions for operator

1. **Approve the 6-month Binance fetch?** (Free, public, no auth — just confirming the data window is acceptable.) Recommended: yes.
2. **Maker-only or maker+taker A/B?** Recommended: run both, since the maker-vs-market comparison *is* the C3 viability question.
3. **Gate thresholds G1–G7 — accept as drafted or tune?** Recommended: accept as drafted for C3; they're deliberately conventional. Tune later if they prove mis-calibrated against real graduations.

---

## References

- B.1.5 break-even sweep + Phase 3.5 verdicts: memory `aaats-2026-05-27-b15-phase35-breakeven`; spec `docs/specs/b15_backtest_harness.md`.
- C3 strategy source: [trading/altcoin_reversion.py](../../trading/altcoin_reversion.py).
- Existing C3 replay (naive cost model this phase replaces): [tools/backtest/c3_replay.py](../../tools/backtest/c3_replay.py).
- NT vs AAATS comparison + borrow plan: [2026-05-26_nautilus_trader_comparison.md](2026-05-26_nautilus_trader_comparison.md).
- NautilusTrader docs: https://nautilustrader.io/docs/
- Live-flip rebuild plan (Track C this feeds): [2026-05-22_live_flip_rebuild_plan.md](2026-05-22_live_flip_rebuild_plan.md).
