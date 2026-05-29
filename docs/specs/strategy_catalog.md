# AAATS Strategy Catalog

> **STATUS 2026-06-01 — ALL STRATEGIES CLOSED-NO-GO FOR LIVE (research-bed mode).**
> No strategy in this catalog is a live-flip candidate. The directional-crypto edge
> program is terminally closed: every class tested — C1 stat-arb, C6 bollinger,
> C3 altcoin-reversion (spot **and** perp), C7 funding-carry, TSMOM momentum, and the
> C3+TSMOM ensemble — **failed an out-of-sample, null-controlled robustness test**
> (final arbiter: the 36mo/15-fold walk-forward, [NO-GO verdict](../decisions/2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md)).
> These strategies continue to run **paper-only** in the D.5 monitored research bed;
> none receives real capital. Reactivation of any class requires a NEW pre-registered
> thesis with its own committed robustness gate — not a re-run of the closed program.
> (C5b funding-arb remains separately HALTED at source since 2026-05-15.)

Generated 2026-05-24 from `trading/*.py`, `trading/live_paper_runner.py`, and `runtime/paper_trades.db`.

This catalog covers the **direct-execution crypto strategies** (`C1`–`C6`, `C5b`) wired into `trading.live_paper_runner.run_crypto`. The `strategies/` package (momentum/, mean_reversion/, volatility/, regime/, etc.) holds signal-generation libraries used by the ensemble voter — they are not first-class execution strategies and are not enumerated here. The India pair `N1_stat_arb_india` is wired into `run_india` but the India market is currently operator-halted (`data/halt_state.json` → `india: true`).

## Caveat on PnL window

`runtime/paper_trades.db` was reset on 2026-05-23 as the baseline for the 30-day D.5 operator-away soak (memory: `project_aaats_d5_soak_window.md`). The "last 30 days" window therefore contains only **~26 hours of trade history** (oldest row 2026-05-23T15:07Z, newest 2026-05-24T12:40Z, 16 rows total). Win-rate and PnL numbers below should be read as an early soak snapshot, not a steady-state estimate.

## Catalog

### C1 — `stat_arb` (BTC/USDT ↔ ETH/USDT cointegrated pair)
- **File:** [trading/stat_arb.py](../../trading/stat_arb.py)
- **Entry:** Open long-A / short-B when the 30-bar rolling z-score of `log(BTC) − log(ETH)` falls below −1.8 (or above +1.8, opposite leg), gated by a weekly Engle-Granger cointegration p-value ≤ 0.05 and 14-day rolling correlation ≥ 0.80.
- **Exit:** Close the pair when |z| < 0.35 (mean reversion), z hits the hard stop ±2.8 (spread blowout), or hold time exceeds 48 hours (crypto) / 5 hours (India intraday).
- **Timeframe:** 1H bars, 30-bar rolling window.
- **Enabled in production?** **Yes** — [trading/live_paper_runner.py:2013-2022](../../trading/live_paper_runner.py#L2013-L2022) wires `run_stat_arb_crypto` into every crypto cycle. India variant wired at [live_paper_runner.py:1830-1837](../../trading/live_paper_runner.py#L1830-L1837) but India market is operator-halted.
- **Closes / Wins / WR / PnL (last 30d):** 4 closes / 2 wins / **50% WR** / +$0.0285 cumulative (avg +$0.0071/close).

### C2 — `momentum_breakout` (4H BTC + ETH breakout)
- **File:** [trading/momentum_breakout.py](../../trading/momentum_breakout.py)
- **Entry:** On a 4H bar close, go long when `close > 20-bar rolling high` AND `RSI(14) > 52` AND `volume > 1.4× 20-bar avg`, gated by 4H EMA(12) > EMA(26) regime filter and Fear & Greed > 40.
- **Exit:** Whichever fires first — +2.0% take-profit, −1.2% hard stop, +0.8% time stop after 8 hours, or stagnation exit if absolute move < 0.3% after one full 4H bar.
- **Timeframe:** 4H bars (resampled from 1H feed).
- **Enabled in production?** **Yes** — [live_paper_runner.py:2036-2043](../../trading/live_paper_runner.py#L2036-L2043).
- **Closes / Wins / WR / PnL (last 30d):** 0 closes / 0 wins / **n/a** / $0 (no entries fired since 2026-05-23 reset — 4H regime + breakout gates have not aligned in the window).

### C3 — `altcoin_reversion` (altcoin vs BTC beta-spread mean reversion)
- **File:** [trading/altcoin_reversion.py](../../trading/altcoin_reversion.py)
- **Entry:** Long an altcoin (SOL / LINK / AVAX / DOT plus scanner picks) when 60-bar rolling z-score of `log(ALT/BTC)` falls below −1.6, gated by HMM regime ≠ BEAR, BTC RSI(14) > 35, BTC.D cycle-on-cycle rise < 0.8%, and not on the persistent loss-leader denylist (`OP, ARB, PUMP, FET, LUNC`).
- **Exit:** Trailing exit once max_z ≥ −0.3 then drops 0.4 z-units from peak; or hard stop at z = −2.6; or time stop at 24 hours; or extreme overshoot at z ≥ +0.5. Stop-out trades trigger a 24h symbol cooldown.
- **Timeframe:** 1H bars, 60-bar rolling window (~2.5 days).
- **Enabled in production?** **Yes**, but gated each cycle by sentiment (skip on extreme greed) — [live_paper_runner.py:2125-2139](../../trading/live_paper_runner.py#L2125-L2139). Entry symbols come from the scanner-first pipeline (`markets.crypto.scanner`/`allocator`) with the hardcoded `SYMBOLS` list as fallback.
- **Closes / Wins / WR / PnL (last 30d):** 0 closes / 0 wins / **n/a** / $0 (3 BUYs still open — TON, MEGA, SAHARA; no exits yet since 2026-05-23 reset).

### C5b — `funding_arb` (delta-neutral spot+perp funding-rate harvest)
- **File:** [trading/funding_arb.py](../../trading/funding_arb.py)
- **Entry:** Open paired position (long BTC/ETH spot + short BTC/ETH perpetual) per symbol when 8H perpetual funding rate ≥ +0.04% (`ENTRY_RATE_THRESHOLD = 0.0004`). $25 per leg, $50 per symbol, up to 2 symbols.
- **Exit:** Close both legs when funding rate drops below +0.02% (`EXIT_RATE_THRESHOLD = 0.0002`) or hold age exceeds 14 days.
- **Timeframe:** Funding settles every 8 hours (3 payments/day); state checked every crypto cycle (15 min).
- **Enabled in production?** **No — disabled at source.** Call site is commented out at [live_paper_runner.py:2024-2033](../../trading/live_paper_runner.py#L2024-L2033) (HALTED 2026-05-15 per `docs/known_issues/2026-05-15_c5b_halt.md`). The asymmetric $25 BUY vs $50 SELL recording would fire the share-equality assertion on every close; re-enable after the unified-ledger Q1–Q4 spec resolves dual-leg accounting.
- **Closes / Wins / WR / PnL (last 30d):** n/a — strategy disabled, 0 trades.

### C6 — `bollinger_range` (BTC/ETH/SOL + scanner picks, range-bound oversold bounce)
- **File:** [trading/bollinger_range.py](../../trading/bollinger_range.py)
- **Entry:** Go long when ALL of the following hold on the 1H bar — regime == `RANGE_BOUND`, %B(20, 2σ) < 0.15, RSI(14) < 32, last 4-bar avg volume > 0.6× 20-bar avg, and no existing open position in that symbol from any strategy.
- **Exit:** Whichever fires first — %B ≥ 0.50 (midline reversion), PnL ≥ +1.5% (take-profit), PnL ≤ −1.0% (hard stop), age ≥ 12 hours (time stop), or regime flip to `TREND_*`.
- **Timeframe:** 1H bars, 20-bar Bollinger window.
- **Enabled in production?** **Yes**, but gated each cycle by sentiment (skip on extreme greed) — [live_paper_runner.py:2144-2158](../../trading/live_paper_runner.py#L2144-L2158). Max 2 concurrent. Entry symbols come from the scanner pipeline with hardcoded `SYMBOLS = [BTC/USDT, ETH/USDT, SOL/USDT]` as fallback.
- **Closes / Wins / WR / PnL (last 30d):** 2 closes / 1 win / **50% WR** / +$0.1608 cumulative (avg +$0.0804/close).

## Summary table

| ID | File | Universe | Timeframe | Enabled? | Closes (30d) | WR | Sum PnL (30d) |
|---|---|---|---|---|---|---|---|
| C1 | `trading/stat_arb.py` | BTC/USDT ↔ ETH/USDT pair | 1H, 30-bar | Yes (crypto); India halted | 4 | 50% | +$0.0285 |
| C2 | `trading/momentum_breakout.py` | BTC/USDT, ETH/USDT | 4H, 20-bar | Yes | 0 | n/a | $0 |
| C3 | `trading/altcoin_reversion.py` | SOL/LINK/AVAX/DOT + scanner picks | 1H, 60-bar | Yes (sentiment-gated) | 0 | n/a | $0 (3 still open) |
| C5b | `trading/funding_arb.py` | BTC/USDT spot+perp, ETH/USDT spot+perp | 8H funding | **No — commented out** | 0 | n/a | $0 |
| C6 | `trading/bollinger_range.py` | BTC/ETH/SOL + scanner picks | 1H, 20-bar | Yes (sentiment-gated) | 2 | 50% | +$0.1608 |

Totals (last ~26h of data since 2026-05-23 reset): **6 closes, 3 wins, ~50% WR, +$0.189 cumulative PnL.**
