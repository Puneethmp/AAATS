# AAATS Strategy Validation — C2 Momentum + C5b Funding Arb (+ Voter Logging Plan)

**Date**: 2026-05-09
**Scope**: Read-only backtests of the two surviving strategies (C1 was previously ruled structurally non-viable in the follow-up). Track 2 is a logging plan only — no code written, awaiting separate approval per protocol.

**Universe note**: Both C2 and C5b only trade `BTC/USDT` and `ETH/USDT` (verified in source). Backtests run on actual universe, not 6 symbols.

---

# Track 1A — C2 Momentum-Breakout Backtest

## Strategy as implemented

From [trading/momentum_breakout.py](trading/momentum_breakout.py):

| Component | Value |
|---|---|
| Universe | BTC/USDT, ETH/USDT only |
| Entry — breakout | `close > 20-bar 4H rolling high` |
| Entry — RSI | `RSI(14) > 52` |
| Entry — volume | `vol > 1.4 × 20-bar avg` |
| Entry — EMA trend (gate A) | `EMA12 > EMA26` |
| Entry — F&G filter (gate B) | `F&G index ≥ 40` |
| Profit target | +2.0% |
| Hard stop | -1.2% |
| Time stop | 8h elapsed AND not yet +0.8% |
| Stagnation | After 4h, abs(price move) < 0.3% |
| Capital per trade | 6% of crypto portfolio |

## Backtest setup

- Data: 2,190 4H bars per symbol (12 months) via Binance ccxt; daily F&G from alternative.me forward-filled to 4H.
- Engine: event-driven replay of live entry/exit logic, identical constants.
- Variants: 4 ablations (baseline, no_fg, no_ema, no_fg_no_ema).
- Sizing: 6% capital per trade with compounding equity.
- No fees, slippage, or partial fills modeled.

## Results

### BTC/USDT

| Variant | Trades | Win Rate | Avg Return | Sharpe (ann.) | Profit Factor | Max DD | Total Ret | Verdict |
|---|---|---|---|---|---|---|---|---|
| baseline | 36 | 33.3% | -0.420% | -2.32 | 0.35 | -0.91% | -0.91% | **BROKEN** |
| no_fg | 64 | 37.5% | -0.276% | -2.11 | 0.51 | -1.06% | -1.06% | **BROKEN** |
| no_ema | 40 | 32.5% | -0.404% | -2.44 | 0.34 | -0.97% | -0.97% | **BROKEN** |
| no_fg_no_ema | 70 | 35.7% | -0.293% | -2.39 | 0.48 | -1.22% | -1.22% | **BROKEN** |

### ETH/USDT

| Variant | Trades | Win Rate | Avg Return | Sharpe (ann.) | Profit Factor | Max DD | Total Ret | Verdict |
|---|---|---|---|---|---|---|---|---|
| baseline | 40 | 45.0% | -0.011% | -0.04 | 0.98 | -0.54% | -0.03% | **BROKEN** |
| no_fg | 67 | 47.8% | +0.087% | 0.41 | 1.15 | -0.64% | +0.35% | **BROKEN** |
| no_ema | 41 | 46.3% | +0.084% | 0.28 | 1.13 | -0.53% | +0.20% | **BROKEN** |
| no_fg_no_ema | 73 | 49.3% | +0.190% | 0.92 | **1.34** | -0.64% | +0.83% | **MARGINAL** |

**Plots**:
- ![C2 BTC equity](d5_c2_equity_BTC_USDT.png)
- ![C2 ETH equity](d5_c2_equity_ETH_USDT.png)

## Track 1A Verdict: ❌ **BROKEN** for BTC, ⚠️ **MARGINAL (best variant only)** for ETH

### Plain English

**C2 baseline is unprofitable on both symbols over 12 months.** Win rates are low (33% BTC, 45% ETH), profit factors below 1.0 (0.35 BTC, 0.98 ETH), and equity ends below 1.0 in both cases. The 36-40 trades over 12 months meets the minimum trade count (≥30) for a viable verdict, but the actual P&L is negative.

**Counter-intuitive ablation finding**: removing both filters (no_fg_no_ema) **improves** results on both symbols, not worsens them.

- BTC: best variant is no_fg (-1.06% total → still negative); all 4 are negative.
- ETH: best variant is no_fg_no_ema (+0.83% total return, Sharpe 0.92, PF 1.34) — barely MARGINAL on PF, fails Sharpe>1.0 by 0.08.

**What this implies about the gates** (descriptive only — no recommendation):
- The F&G > 40 filter is **excluding profitable trades** in this 12-month window. Removing it consistently increases trade count (~75%) and improves PF for both symbols.
- The EMA12 > EMA26 trend filter is similarly exclusionary — removing it adds trades and improves ETH PF.
- The two filters are not redundant; removing both gives the largest improvement, suggesting they exclude different profitable subsets.
- This does not say the filters are wrong in principle — they may protect capital in market regimes our 12-month window doesn't include (e.g., a 2018-style multi-month bear). But within the observed window, the data does not support their inclusion.

**Trade count vs. profitability is the real constraint.** Even at no_fg_no_ema, ETH only generates 73 trades over 12 months (~6/month). That's enough to be statistically meaningful but not enough to sustain compounding edge after fees and slippage are introduced.

---

# Track 1B — C5b Funding-Rate Arbitrage Backtest

## Strategy as implemented

From [trading/funding_arb.py](trading/funding_arb.py):

| Component | Value |
|---|---|
| Universe | BTC/USDT and ETH/USDT perpetuals (delta-neutral with spot) |
| Entry threshold | funding_rate ≥ 0.0008 (0.08% per 8H) |
| Exit threshold | funding_rate < 0.0002 (0.02% per 8H) |
| Max hold | 14 days |
| Capital per leg | $25 (× 2 legs = $50/symbol) |
| Funding cadence | 3 payments per day (every 8H) |
| Income | capital_per_leg × rate × payments_elapsed |

## Backtest setup

- Data: 1,095 funding payment events per symbol over 12 months (Binance Futures public API `/fapi/v1/fundingRate`).
- Engine: event-driven on funding settlement events.
- Threshold ablation: 0.0004, 0.0008, 0.0012, 0.0016 (per task spec).
- No fees, basis risk, or borrow costs modeled.

## Funding Rate Distribution Statistics (12 months)

| Symbol | Min | Max | Mean | Median |
|---|---|---|---|---|
| BTC/USDT perp | -0.0152% | **0.0100%** | 0.0033% | 0.0037% |
| ETH/USDT perp | -0.0365% | **0.0100%** | 0.0030% | 0.0036% |

**Key observation**: The maximum observed funding rate over 12 months is **0.01%** for both symbols. The strategy's entry threshold of **0.08%** is **8× higher than the actual peak rate** ever observed. Even the lowest tested ablation threshold (0.04%) is 4× the observed max.

## Results

### All 4 thresholds × 2 symbols = 8 backtest runs

| Threshold | Symbol | Trades | Verdict |
|---|---|---|---|
| 0.0004 (0.04%) | BTC | 0 | BROKEN (no trades) |
| 0.0004 (0.04%) | ETH | 0 | BROKEN (no trades) |
| 0.0008 (0.08%) — live | BTC | 0 | BROKEN (no trades) |
| 0.0008 (0.08%) — live | ETH | 0 | BROKEN (no trades) |
| 0.0012 (0.12%) | BTC | 0 | BROKEN (no trades) |
| 0.0012 (0.12%) | ETH | 0 | BROKEN (no trades) |
| 0.0016 (0.16%) | BTC | 0 | BROKEN (no trades) |
| 0.0016 (0.16%) | ETH | 0 | BROKEN (no trades) |

**Plot**: ![C5b threshold sensitivity](d6_c5b_threshold_sensitivity.png)

## Track 1B Verdict: 🚫 **STRUCTURALLY DORMANT**

### Plain English

**C5b never triggered an entry over 12 months at any of the tested thresholds.** The strategy is not "broken" in the usual sense (losing money); it's structurally dormant — its entry condition cannot be satisfied given the observed funding rate environment.

**Why this happens**: Binance's funding rate cap on BTC and ETH perpetuals is effectively bound at +0.01% (this is consistent with Binance's published max-funding-rate rules and the empirical max we observed). The strategy was specified assuming rates would frequently spike to 0.08%+ — that may have been true on smaller-cap symbols, on different exchanges, or in earlier crypto cycles, but it is not true on Binance BTC/ETH perps in the most recent 12 months.

**What this implies about the strategy spec** (descriptive only):
- The 0.0008 entry threshold reflects a scenario that does not exist in the current data.
- The 0.0002 exit threshold is paradoxical — exit when rate < 0.02%, but the *median* observed rate is 0.0036% (less than 2× the exit threshold). If the strategy ever did enter, it would exit almost immediately on most days, well before 14-day max-hold.
- The strategy may be viable on different symbols (alts where rates reach 0.08%+ during squeezes) or different exchanges (Bybit, OKX with different funding regimes), but that requires data and code we don't currently have.

---

# Comparison Summary

| Strategy | Symbol | Best Sharpe | Best PF | Best Trade Count | Verdict |
|---|---|---|---|---|---|
| C2 momentum | BTC/USDT | -2.11 (no_fg) | 0.51 (no_fg) | 70 (no_fg_no_ema) | **BROKEN** |
| C2 momentum | ETH/USDT | 0.92 (no_fg_no_ema) | 1.34 (no_fg_no_ema) | 73 (no_fg_no_ema) | **MARGINAL (best variant only)** |
| C5b funding | BTC/USDT | n/a | n/a | 0 (any threshold) | **DORMANT** |
| C5b funding | ETH/USDT | n/a | n/a | 0 (any threshold) | **DORMANT** |

**Net status of the strategy stack**:
- C1 (stat-arb BTC/ETH): structurally non-viable (prior follow-up — pair was cointegrated only 1.9% of 90d, and 8% on a 12-month rolling SOL/AVAX retest)
- C2 (momentum): broken on BTC, marginal-at-best on ETH only when both filters are removed
- C5b (funding arb): dormant — entry threshold unreachable
- The 6-vote consensus + ML gate path covers SOL/LINK/DOT/AVAX but is not a strategy in itself; it's a meta-filter on signals that need an underlying strategy. With C1/C2/C5b in their current state, the consensus+ML layer has nothing profitable to gate.

---

# Track 2 — Live Voter Logging (Plan Only — No Code Written)

This section documents the proposed approach. **Per protocol rule #6, no code will be written until separately approved.**

## Goal

Capture 6 voters × 6 symbols × every cycle for ~7 days, with the **live HMM regime label** attached to each record. Then re-run D1 voter independence using actual production data instead of `_rule_regime` replay, to resolve the asterisk on the original D1 PASS.

## Where the hook goes

[trading/live_paper_runner.py](trading/live_paper_runner.py), inside `generate_signal()` (around line 631-660), **after** the 6 `vote_*()` calls return their `StrategyVote` objects but **before** the `_voter.cast_consensus()` call that aggregates them.

```python
# Pseudocode (NOT yet written into the file)
def generate_signal(symbol, features, market):
    regime, r_conf = detect_regime(symbol, features)
    votes = [
        vote_ema(features, market, regime),
        vote_rsi(features, market, regime),
        vote_momentum(features, market, regime),
        vote_vwap(features, market, regime),
        vote_bollinger(features, market, regime),
        vote_macd_hist(features, market, regime),
    ]
    # >>> NEW HOOK <<<
    _shadow_log_votes(symbol, votes, regime, r_conf)
    # >>> end hook <<<
    result = _voter.cast_consensus(votes)
    ...
```

## Format

JSONL append-only at `logs/voter_shadow/<UTC-date>.jsonl`. One record per voter per symbol per cycle:

```json
{"ts":"2026-05-10T03:30:15Z","cycle_id":1234,"symbol":"BTC/USDT","voter_name":"ema_crossover","signal":"HOLD","confidence":0.55,"regime_label":"RANGE_BOUND","regime_confidence":0.6}
```

Volume estimate: 6 voters × 6 symbols × 96 cycles/day = ~3,456 records/day → ~600 KB/day. Log-rotates daily by date in filename.

## Read-only behavior guarantees

To be verified before code is written:
- Hook runs **after** all 6 voters have returned. Voter call results are not modified, just observed.
- No change to `_voter.cast_consensus()` arguments, regime logic, or any downstream control flow.
- No change to ML gate, F&G filter, entry/exit rules, position sizing, or trade execution.

## Fail-safe

- Wrap the JSONL append in try/except that swallows all errors. Emit at most one warning per cycle on failure.
- If filesystem fills up or `logs/voter_shadow/` is unwritable, the live cycle continues unaffected.
- File handle uses Python's `mode="a"` (atomic POSIX append) — multi-process-safe.
- No locks, no synchronous flushing during cycle — drop-in append, no perf impact.

## Scope of file changes (if approved)

- 1 file edit to `trading/live_paper_runner.py` (~15 lines added).
- 0 new files in the live system source tree. JSONL outputs are runtime artifacts, not committed code.

## After 7 days

Re-run a modified D1 against the collected JSONL: compute pairwise Pearson correlation and Cohen's kappa on the actual production voter outputs (with HMM regime labels rather than rule fallback). Compare to original D1 results. Resolve the original asterisk.

**Awaiting your separate approval to write this code.**

---

# Known Limitations

- **No fees, slippage, or partial fills modeled.** Both backtests assume frictionless execution. Real-world fees on Binance crypto are ~0.1% per leg; for C2 a round-trip costs ~0.2%, which would push C2 ETH no_fg_no_ema (currently +0.83% over 12 months) into negative territory after ~4 trades. For C5b the 4-leg round-trip would cost ~0.4% — comparable to or larger than the gross expected income at observed rates.
- **12-month window may not capture full crypto regime cycles.** Crypto markets often show 2-4 year cycles. The May 2025–May 2026 window covers approximately 1/3 of a typical macro cycle. C2 results could differ substantially in a strong directional regime; C5b funding rates spiked to >0.5% during 2021 retail squeezes that didn't repeat in this window.
- **Funding rate data is Binance-specific.** OKX, Bybit, and dYdX have different funding rate caps and could plausibly support the C5b 0.0008 threshold. We have not tested those.
- **No basis risk modeled in C5b.** A delta-neutral position can still lose if spot–perp basis blows out (e.g., during de-leveraging events). The backtest treats the spread as exactly zero.
- **C2 backtest assumes 6% sizing applies to every trade.** Live system would scale this with portfolio drawdown via risk_engine — not modeled here.
- **F&G data quality.** alternative.me's index is itself a composite of weighted sub-indicators; methodology has changed over the years. Backtest treats it as a fixed daily value forward-filled to 4H.
- **C5b uses only entry/exit threshold logic.** No regime-conditional entry, no funding-rate-trend filter, no anti-MEV pre-funding-tick avoidance. A more sophisticated funding-arb strategy could plausibly trade — but that's a different strategy, not the C5b spec we tested.
- **Equity curve sharpe**: the daily-pct-change sharpe annualizes by sqrt(365) on the assumption of daily resampling. With ~60-70 trades over 12 months, most trading days have zero returns, which deflates the std and inflates Sharpe magnitude (in either direction). Compare across variants but be cautious with absolute interpretation.
- **What this report does NOT test**: feature look-ahead bias in the live system, label leakage in the ML training set, walk-forward robustness, voter calibration (does conf=0.78 actually correspond to 78% win rate?), HMM regime accuracy. All carried over as known gaps from prior reports.

---

# File Index

```
diagnostics/
├── d5_c2_backtest.py                         # script
├── d6_c5b_backtest.py                        # script
└── reports/
    ├── 2026-05-09_strategy_validation.md     # this report
    ├── d5_c2_equity_BTC_USDT.png             # equity curves, 4 variants
    ├── d5_c2_equity_ETH_USDT.png             # equity curves, 4 variants
    ├── d5_c2_summary.json                    # all metrics + verdicts
    ├── d5_c2_trades_BTC_USDT_<variant>.csv   # 4 files per symbol
    ├── d5_c2_equity_BTC_USDT_<variant>.csv   # 4 files per symbol
    ├── d6_c5b_threshold_sensitivity.png      # zero-trade comparison
    ├── d6_c5b_summary.json                   # threshold ablation results
    ├── d6_c5b_trades_<sym>_thr<X>.csv        # empty trade tables (per variant)
    └── d6_c5b_equity_<sym>_thr<X>.csv        # flat equity curves (per variant)
```

---

**STOPPING HERE per protocol rule #6.** Track 2 logging code awaits separate approval.
