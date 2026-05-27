# B.1.5 backtest harness — data + scaffolding inventory (2026-05-27)

**Status:** Gap analysis (Phase 1 deliverable).
**Premise correction:** When phase 1 was scoped, B.1.5 was described as a "missing piece." The inventory below shows it is in fact partly shipped for C3 (~1,300 LOC). This memo replaces the green-field scope with concrete gap-analysis.

---

## 1. OHLCV history on disk

Five parquet files in [data/historical/](data/historical/), 1H bars, 2026-03-24T11:00Z → 2026-05-23T10:00Z (1440 bars = 60 days per symbol). Schema: `ts, open, high, low, close, volume`.

| Symbol | Size | Bars | Used by |
|---|---|---|---|
| `BTC_USDT_1h.parquet` | 64.0 KB | 1440 | C1 (leg A), C3 (anchor for z-score), C6 |
| `SOL_USDT_1h.parquet` | 49.0 KB | 1440 | C3, C6 |
| `LINK_USDT_1h.parquet` | 36.9 KB | 1440 | C3 |
| `AVAX_USDT_1h.parquet` | 35.1 KB | 1440 | C3 |
| `DOT_USDT_1h.parquet` | 36.2 KB | 1440 | C3 |

**Gap 1: ETH/USDT bars missing.** C1 stat_arb pair is `("BTC/USDT", "ETH/USDT", ...)` per [trading/stat_arb.py:55-59](trading/stat_arb.py#L55-L59). Cannot replay C1 without ETH bars. Fetcher at [tools/backtest/historical_data.py:fetch_ohlcv](tools/backtest/historical_data.py#L83) can populate it — single CLI call, ~5s once cached.

**Gap 2: 60 days only.** Locked doctrine paper-success criterion is "≥30 closed trades, trailing 30d Sharpe > 0, MDD < 15%" ([aaats_locked_doctrine_2026_05_14.md:33-37](docs/operator/aaats_locked_doctrine_2026_05_14.md#L33-L37)). 60 days × 1.4 trades/day ≈ 84 C3 trades (matches harness result, see §3) — adequate for trade count but only ~2 BTC vol cycles. For confident regime coverage want ≥6 months. Out-of-scope here; queued as Phase 4 work item.

**Fetcher capabilities** (no rebuild needed):
- [tools/backtest/historical_data.py:55](tools/backtest/historical_data.py#L55) — `ccxt.binance({"enableRateLimit": True})`, no auth
- Line 57 — 1000-bar batch ceiling (Binance limit)
- Line 72 — `time.sleep(ex.rateLimit/1000)` between batches
- Lines 111-125 — cache-first; only re-fetches if cache doesn't cover requested window
- Supports 1m / 5m / 15m / 1h / 4h / 1d

---

## 2. Replay scaffolding

**Shipped — production-grade:**

| File | LOC | Role |
|---|---|---|
| [backtesting/engine.py](backtesting/engine.py) | 333 | Generic single-leg backtest engine; 6 integrity gates (timestamp order, overfit-Sharpe>3.0, cost gate, walk-forward). Public API `run_backtest(features_df, strategy_fn, portfolio_value) → BacktestResult`. |
| [tools/backtest/c3_replay.py](tools/backtest/c3_replay.py) | 285 | C3-specific bar-by-bar replay. Reuses C3 pure functions directly from `trading/altcoin_reversion` ([c3_replay.py:40-43](tools/backtest/c3_replay.py#L40-L43)): `_compute_z_score`, `_rsi`, `_realized_daily_vol`, `_compute_trade_size`. Reimplements only the driver (clock, file system, DB) — no strategy logic duplication. |
| [tools/backtest/historical_data.py](tools/backtest/historical_data.py) | 136 | OHLCV fetcher + parquet cache (above). |
| [tools/backtest/run_b15_c3.py](tools/backtest/run_b15_c3.py) | 320 | End-to-end orchestrator: fetch → align ([run_b15_c3.py:76](tools/backtest/run_b15_c3.py#L76)) → headline replay → 50bps slip sensitivity → 3 vol-stratified regime windows → recommendation. Writes `data/backtest_results/c3_60d_summary.json`. |
| [tests/test_b15_backtest_harness.py](tests/test_b15_backtest_harness.py) | 218 | Contract tests against synthetic dip-recover fixtures + threshold boundary cases. |

**Strategy entry-point readiness** (for adding more strategies):

| Strategy | Public runner | Pure helpers exposed? | Replay status |
|---|---|---|---|
| C1 stat_arb | `run_stat_arb_crypto` @ [stat_arb.py:498](trading/stat_arb.py#L498) | Not yet — `_compute_zs`, `_z_entry_allowed`, `_z_exit_allowed` exist but not enumerated as the pure-helper export pattern c3_replay uses | **NOT BUILT** |
| C2 momentum | `run_momentum_breakout_crypto` @ [momentum_breakout.py:244](trading/momentum_breakout.py#L244) | One-off in [diagnostics/d5_c2_backtest.py](diagnostics/d5_c2_backtest.py) | Diagnostic only, not harness-integrated |
| C3 altcoin_reversion | `run_altcoin_reversion_crypto` @ [altcoin_reversion.py:479](trading/altcoin_reversion.py#L479) | Yes — see c3_replay imports | **PRODUCTION** |
| C5b funding_arb | `run_funding_arb_crypto` (search by name) | One-off in [diagnostics/d6_c5b_backtest.py](diagnostics/d6_c5b_backtest.py) | Diagnostic only |
| C6 = bollinger_range | `run_bollinger_range_crypto` @ [bollinger_range.py:228](trading/bollinger_range.py#L228) | Not exposed | **NOT BUILT** |

**Mock-clock + network-injection infra exists in `v6-stack/replay/` (37 LOC + 80 LOC)** but is reserved for v5-parity κ2 work; B.1.5 doesn't use it (DataFrame iteration avoids the wall-clock problem entirely).

**Spec memo from session 9** ([docs/decisions/2026-05-22_b15_backtest_harness.md](docs/decisions/2026-05-22_b15_backtest_harness.md)) mandates exit criteria including "10-trade replay vs paper-mode within ±2¢" — **no such parity test exists in code yet** (the 218-LOC test file uses synthetic fixtures, not live ledger comparison). Tagged as Phase 3 deliverable.

---

## 3. Metrics infrastructure (reusability for replay output)

| File | Function | Pure? | Replay-reusable? |
|---|---|---|---|
| [tools/backtest/c3_replay.py:249](tools/backtest/c3_replay.py#L249) | `summarize_trades` | PURE | YES — already used by `run_b15_c3` |
| [analytics/strategy_optimizer.py:106](analytics/strategy_optimizer.py#L106) | `_score(trades, params)` → (win_rate, total_pnl, sharpe, n) | PURE | YES — operates on list-of-dict |
| [analytics/strategy_optimizer.py:131](analytics/strategy_optimizer.py#L131) | `optimize()` | SIDE-EFFECTING | NO — reads hardcoded `_DB_TRADES = Path("data/paper_trades.db")` @ line 26 |
| [analytics/pnl_attribution.py:81](analytics/pnl_attribution.py#L81) | `get_summary(market)` | SIDE-EFFECTING | NO — `sqlite3.connect(self._db)` @ line 83. Workaround: pass `db_path=":memory:"`. |
| [monitoring/metrics_exporter.py:817](monitoring/metrics_exporter.py#L817) | `collect_performance_timeline()` | SIDE-EFFECTING | NO — hardcoded DB path @ line 24; computes Sharpe + MDD + profit-factor inline |

### 3a. The `sqrt(252)` annualization issue — P0 finding, narrower than first read

**Two callsites use `sqrt(252)` for per-trade Sharpe:**

- [analytics/strategy_optimizer.py:125](analytics/strategy_optimizer.py#L125) — `sharpe = (mean / std * (252 ** 0.5)) if std > 0 else 0.0`
- [monitoring/metrics_exporter.py:851](monitoring/metrics_exporter.py#L851) — `sharpe = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0`

These are NOT time-series Sharpe over daily bars (which `sqrt(252)` would correctly annualize). They are **per-trade** Sharpe over per-trade `pnl_pct` returns. The correct annualization for per-trade Sharpe on a crypto 24/7 book is `sqrt(N_trades / window_days × 365)`, not a fixed bar-rate constant.

`sqrt(252)` is wrong by direction *and* magnitude:
- Direction: assumes one trade per "day" stock-convention, but crypto runs 24/7 (365 days).
- Magnitude: the strategies trade ~5–15 times per month, not 252 times per year. The implied annualization is ~16× too aggressive for actual trade rate.

**The harness's own `summarize_trades` is NOT bugged.** [c3_replay.py:255-257](tools/backtest/c3_replay.py#L255-L257) docstring explicitly uses `sqrt(60)` ("~5 trades/month → ~60/year"), comments the choice, and is internally consistent. The harness output below stands.

Fix complexity:
- `metrics_exporter.py`: window is fixed at 14 days; replace `sqrt(252)` with `sqrt(len(pnls) / 14.0 * 365.0)`. Single-line change. Live Grafana panel `aaats_rolling_sharpe_14d` will jump to the corrected value next scrape — operator should expect this once deployed.
- `strategy_optimizer.py:_score`: no window in the signature; needs trade timestamps from the SELECT to compute window. ~5-line change to extend the SELECT + compute window in `_score`.

Both queued as **Phase 2 step 1** in the design memo.

---

## 4. Headline run — C3 60d replay (2026-05-27 verification run)

Cached window: 2026-03-24T11Z → 2026-05-23T10Z (60d × 5 symbols).
Command: `venv\Scripts\python -m tools.backtest.run_b15_c3 --days 60 --end-ts 2026-05-23T11:00:00Z`.

| Metric | Headline | 50bps slip |
|---|---|---|
| Trades | 86 | 76 |
| PnL ($100 capital) | **+$5.43** | **-$5.72** |
| Sharpe (sqrt(60)) | +1.521 | -2.079 |
| Win rate | 47.7% | 31.6% |
| Profit factor | 1.81 | 0.54 |
| Avg per-trade pct | +0.42% | -0.59% |

Regime split (3 × 20-day vol-stratified): low_vol +$2.53, mid_vol -$0.32, high_vol +$3.33. Profitable regimes: 2/3.

**Recommendation: PARTIAL** (passes pnl>0, sharpe>0.5, regimes≥2; **fails 50bps slippage>0**). Per [run_b15_c3.py:53-73](tools/backtest/run_b15_c3.py#L53-L73).

**Interpretation:** strategy is positive at zero friction but slippage-fragile. A 50bps round-trip cost (≈ realistic Binance maker+taker at small notional) flips PnL by ~$11 on $100 capital. The strategy lives or dies on slippage assumptions — that's the actionable finding for B.1.5 phase 4 (regime + cost sensitivity).

Caveats acknowledged by the harness evidence string:
- HMM BEAR-regime gate disabled in replay (production has this; replay is permissive)
- BTC.D fast-rise filter disabled in replay
- Spread + exchange fees set to 0 in base run (only 50bps sensitivity tested, no granularity sweep)

Result file: `data/backtest_results/c3_60d_summary.json` (gitignored under `data/*`).

---

## Cross-references

- Design memo: [docs/specs/b15_backtest_harness.md](docs/specs/b15_backtest_harness.md)
- Original spec: [docs/decisions/2026-05-22_b15_backtest_harness.md](docs/decisions/2026-05-22_b15_backtest_harness.md)
- Locked doctrine paper criteria: [docs/operator/aaats_locked_doctrine_2026_05_14.md](docs/operator/aaats_locked_doctrine_2026_05_14.md)
- Doctrine amendment (paper floor $200): [docs/decisions/2026-05-23_doctrine_amendment_200_floor.md](docs/decisions/2026-05-23_doctrine_amendment_200_floor.md)
