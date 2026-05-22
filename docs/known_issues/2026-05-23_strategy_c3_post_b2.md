# C3 paper-shadow validation (Phase B.2 post-deploy measurement)

**Status:** PROTOCOL DOCUMENTED, AWAITING DATA. Re-evaluate 2026-05-29 (7 calendar days from session-3 patch deploy).
**Authored:** 2026-05-22 (session 4).
**Parent plan:** [`docs/decisions/2026-05-22_live_flip_rebuild_plan.md`](../decisions/2026-05-22_live_flip_rebuild_plan.md) Phase B.2.
**Cross-refs:**
- [`docs/known_issues/2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md`](2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md) — pre-patch diagnostic + symbol-halt math.
- [`docs/decisions/2026-05-22_live_flip_rebuild_plan.md`](../decisions/2026-05-22_live_flip_rebuild_plan.md) B.1 triage table — verdict was **PARAM-TUNE + symbol-halt (combined)**.

## Question this memo answers

The C3 PARAM-TUNE + symbol-halt patch (BTC_DOM_FAST_RISE wired in
`_entry_allowed`; `DENYLIST_SYMBOLS = {OP/USDT, ARB/USDT, PUMP/USDT,
FET/USDT, LUNC/USDT}` short-circuiting the ENTRY branch) shipped to the
box in session 3 (commit `52ea322`, post-deploy at ~2026-05-22T15:00Z).
This memo asks: **did the patch reduce realized loss?**

The expected effect, per the session-1 diagnostic:
- pre-patch C3 realized P&L: **−$5.63 over 9 days** (44 SELLs, 27% win rate).
- pre-patch top-5 symbol-halt math: residual P&L without OP/ARB/PUMP/FET/LUNC
  would have been **−$1.22 over 9 days** (78% of the loss avoided).
- expected post-patch P&L per 9-day window: **closer to −$1 than to −$5**,
  assuming market conditions similar to the pre-patch sample.

## Status as of memo authoring (2026-05-22T17:52Z)

The C3 patch is verified active on box source:
- `trading/altcoin_reversion.py:86` declares `DENYLIST_SYMBOLS` frozenset.
- `trading/altcoin_reversion.py:383` reads `BTC_DOM_FAST_RISE` inside
  `_entry_allowed` (the wiring fix that was the headline change).
- `trading/altcoin_reversion.py:665` short-circuits `if sym in DENYLIST_SYMBOLS`.
- `trading/live_paper_runner.py:1755` passes `btc_dom_now=btc_dom` into the
  C3 dispatch site.

Post-patch elapsed time: **~3 hours.** Trade activity in that window:

| Window | C3 SELLs | C3 P&L | C3 BUYs |
|---|---|---|---|
| Pre-patch (2026-05-12 → 2026-05-22T15:00Z) | 47 | **−$5.63** | 60 |
| Post-patch (2026-05-22T15:00Z → 17:41Z) | **0** | **$0.00** | **0** |
| All-time | 47 | −$5.63 | 60 |

Source: `paper_trades.db` on box, queried via `docker exec aaats-paper-crypto
python /tmp/diag_b2_fix.py` 2026-05-22T17:41Z.

**The 0/0/$0 post-patch numbers are NOT a result; they are an
insufficient-sample artifact.** C3's 9-day rate was ~5 trades/day; 3 hours
should produce ~0–1 trades in steady state. Zero is statistically
indistinguishable from the expected post-patch rate.

The denylist + BTC_DOM filter cannot be evaluated against zero post-patch
ENTRY candidates. Need a 7-day window minimum for a meaningful comparison.

### What is observably different vs pre-patch

- `data/c3_btc_dom_cache.json` does NOT exist yet (would be created on
  first cycle where `btc_dom is not None`). Possible interpretations:
    (a) the BTC dominance fetcher returned `None` in the post-deploy
        cycles (network failure, exchange API hiccup);
    (b) C3 had zero candidates in the post-deploy cycles, so
        `run_altcoin_reversion_crypto` never reached the cache-write line
        because no symbol passed entry pre-checks.
  Both are benign. The cache will appear on the first BTC.D-fetching
  cycle where C3 has at least one candidate symbol.
- Scanner output shows `c3=0` candidates in cycle 1 post-deploy. C3 holds
  1 position (`C3=hold(1)` in the runner log), so the strategy is on the
  manage-open branch this cycle, not the entry branch.

## Measurement protocol (locked)

### Baseline (pre-patch, frozen)

```
Window:      2026-05-12T00:00:00Z to 2026-05-22T15:00:00Z (~10 days)
C3 SELLs:    47
C3 P&L:      -$5.63
Win rate:    27%
Per-trade:   avg win +$0.25, avg loss -$0.28, best +$1.04, worst -$1.30
Top-5 worst symbols (OP, ARB, PUMP, FET, LUNC): -$4.42 (78% of loss)
```

### Post-patch evaluation (target: 2026-05-29T15:00:00Z, 7-day window)

Compute the same fields against:
```
SELECT COUNT(*), ROUND(SUM(pnl), 4), AVG(CASE WHEN pnl>0 THEN 1.0 ELSE 0.0 END)
FROM paper_trades
WHERE strategy='C3_altcoin_reversion'
  AND action='SELL'
  AND timestamp >= '2026-05-22T15:00:00Z'
  AND timestamp <  '2026-05-29T15:00:00Z';
```

**Pass criteria:**
- (P1) Post-patch C3 P&L is shallower than pre-patch per-day rate, i.e.,
  > **−$4.40** over 7 days (pre-patch was −$5.63 over ~10d ≈ −$0.56/d).
- (P2) NO denylisted symbol (OP/ARB/PUMP/FET/LUNC) appears as a **BUY**
  in the 7-day window. SELLs of held denylisted positions ARE expected
  (held positions take the manage-open branch which the patch does not
  block). The 5 sym pre-patch positions opened before 2026-05-22T15:00Z
  may still close in this window; their SELL P&L counts toward the
  measured total but does NOT signal a patch failure.
- (P3) `data/c3_btc_dom_cache.json` exists and has a recent mtime (within
  one cycle interval), proving the BTC_DOM filter is in the active path.

**Fail criteria** (any one triggers a re-triage of C3):
- (F1) Post-patch C3 P&L worse than **−$5.00** over 7d (no improvement
  from the patch, indicating the denylist + BTC_DOM filter does not
  capture the loss source).
- (F2) Any denylisted symbol opens a NEW BUY (DENYLIST_SYMBOLS check
  not in the ENTRY path).
- (F3) `c3_btc_dom_cache.json` still missing after 7 days (the filter
  is on a dead code path).

### Fallback: backtest if paper-shadow inadequate

If the 7-day window produces fewer than 10 C3 SELLs (statistically
underpowered), run a backtest harness against the pre-patch + post-patch
strategy code over a longer synthetic window:

- **Harness:** `scripts/backtest_c3_param_sweep.py` does NOT exist yet
  (verified by `glob scripts/backtest*` 2026-05-22). Build one only if
  the paper-shadow comes up short. Reference architecture: the existing
  US-side backtester at `logs/us/backtesting_engine.log` shows
  the conventions; the crypto side has never had a published harness.
- **Inputs:** 30 days of 15-minute OHLCV per C3 universe symbol from
  Binance public REST, plus BTC.D readings from the same source.
- **Compute:** simulate `_entry_allowed` over each symbol+timestamp,
  emit the BUY/SELL decisions, sum the P&L assuming exit-at-mean-reversion
  per the strategy's documented logic. Compare denylist-on vs denylist-off
  + BTC_DOM-on vs BTC_DOM-off (2x2 = 4 variants).

**Estimate:** building the harness is ~1 Sonnet session. Defer until the
7-day window's outcome is known.

## Decision tree (re-evaluation 2026-05-29)

```
                  [Read post-patch P&L from paper_trades.db]
                         |
              +----------+----------+
              |                     |
         >= -$1                 < -$5
         (P1+P2+P3 PASS)        (F1)
         |                      |
         "KEEP, monitor 30d"    "Re-triage: HALT C3 or
         + close memo            replace with a different
                                 mean-reversion strategy"
              |
        -$1 to -$5
        (inconclusive)
         |
         Fall back to backtest harness.
```

## Action needed

NONE this session. Schedule the re-evaluation for **2026-05-29** as a
session 5+ task. Add row "B.2 post-patch evaluation" to next session's
prompt.
