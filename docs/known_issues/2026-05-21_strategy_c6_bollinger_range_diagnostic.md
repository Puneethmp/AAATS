# C6 Bollinger Range — diagnostic memo (2026-05-21)

**Strategy ID:** C6_bollinger_range
**Window:** 2026-05-12 → 2026-05-21 (9 days, paper-crypto)
**Status — Verdict:** KEEP (insufficient data to triage)
**Parent doc:** [`docs/decisions/2026-05-22_live_flip_rebuild_plan.md`](../decisions/2026-05-22_live_flip_rebuild_plan.md) §A, §D

## Summary

C6 produced 5 SELLs over 9 days for $-0.128 realized (parent §A). That is
below the triage-confidence noise floor. The strategy's structural
mechanics (Bollinger %B + RSI + volume + RANGE_BOUND regime) read clean;
the previously surfaced concern is downstream filter starvation (scanner
picks dropped before C6 sees them, per 2026-05-18 audit §P4 row C6 and
§P2 lines 95–101). **5 trades is too small to triage with confidence.**
Recommend KEEP and re-evaluate after 4 consecutive weeks of Phase B.3
soak.

## 1. Evidence: trade volume below triage floor

Per parent §A (all-9d window):

| Metric | C6 value | C3 comparable |
|---|---:|---:|
| Total trades | 10 | 92 |
| SELLs (closed positions) | 5 | 44 |
| Realized P&L (USD) | -0.128 | -5.634 |
| Win rate | 20% (1/5) | 27% (12/44) |
| avgW | +$0.060 | +$0.253 |
| avgL | -$0.047 | -$0.279 |
| Best trade | +$0.060 | +$1.044 |
| Worst trade | -$0.059 | -$1.296 |

5 SELLs is below any reasonable statistical-significance threshold for
WR or EV. A coin-flip with 5 trials produces 20% WR with p>0.3 vs a
"true" 50% strategy — i.e., the observed 20% WR is consistent with a
break-even underlying signal under small-sample noise.

Per-trade magnitudes (~$0.05 W/L) reflect the design intent at
`trading/bollinger_range.py:54`:
```
Per-trade absolute: $7.20 × 0.4% = $0.029  ≈  $0.06–0.20 / 48h gross
Real value: SIGNAL DENSITY for engineering validation, not PnL
```
The realized $-0.128 over 5 SELLs is **within** the strategy's
own-documented expected range.

## 2. Evidence: structural mechanics read clean

1. **Entry gates** — `trading/bollinger_range.py:389-397`:
   - `regime != "RANGE_BOUND"` skip (line 389-390)
   - `%B >= 0.15` skip (line 391-392)
   - `RSI >= 32` skip (line 393-394)
   - `_volume_healthy(df) == False` skip (line 395-397)
   All four gates are AND-composed. Defaults are conservative
   (entry only on deep oversold within range).
2. **Exit hierarchy** — `trading/bollinger_range.py:320-330`:
   ordered by `%B target → take-profit → hard stop → time stop → regime
   flip`. The regime-flip exit only fires after age > 1.0h
   (`trading/bollinger_range.py:329`), which protects against a 1-bar
   HMM flicker forcing a fresh entry out.
3. **Concurrency cap** — `MAX_CONCURRENT = 2` at line 86; combined with
   the cross-strategy "no double-up" check at line 381-386, C6 cannot
   accumulate hidden book risk.
4. **Symbol universe** — hardcoded BTC/ETH/SOL at line 83; scanner picks
   override via the `symbols=` parameter at the call site
   (`trading/live_paper_runner.py:1770`). Both paths feed into the same
   gates. No silent path-divergence found.

## 3. Evidence: the 2026-05-18 audit concern is filter starvation, not strategy bug

Per 2026-05-18 audit `docs/decisions/2026-05-18_strategy_activity_audit.md:95-101`:

> For C6 the scanner picks (ONDO/ARB/APT/CHIP) are **rejected downstream**:
>  - `correlation_guard` skips with `c6 skip ONDO/USDT (cluster OTHER already at cap)`;
>  - `bollinger_range` rejects survivors with `volume below floor — skip`
>    or `trade size $3.73 < min $5.00 — skip`.
>  - Then the strategy iterates a **hardcoded BTC/ETH/SOL** set …
>    nowhere near the extremes Bollinger requires.

This is a *pipeline composition* issue, not a C6 logic bug. The fix lives
in the scanner / correlation_guard / allocator layer, not in
`bollinger_range.py`. The strategy's own gate honesty is intact.

Symbol coverage observed (parent §D): 5 distinct symbols — TRX, EUR,
FIL, ICP, 币安人生/USDT. The unicode-named symbol is an exchange-universe
artifact worth surfacing to scanner triage in B.0.5, but does not
implicate C6 strategy code.

## 4. Why KEEP (and not PARAM-TUNE or HALT)

1. **Loss magnitude $-0.128 over 9 days is statistically indistinguishable
   from zero** at any reasonable confidence interval. There is no "loss
   pattern" to triage.
2. **Parameter sweeps on 5 SELLs over-fit.** Tuning `PCT_B_ENTRY`,
   `RSI_ENTRY`, `TAKE_PROFIT_PCT` on this sample would produce
   data-dredged params indistinguishable from random search.
3. **The C3 trade-density argument cuts the other way for C6**: parent
   §A makes C3 the load-bearing strategy this window. If C3 is
   PARAM-TUNEd successfully in B.2 + B.3, C6 may naturally see more
   eligible RANGE_BOUND windows post-B.3.

## 5. Re-evaluation criteria

Re-triage C6 when **either** holds:

- **(a)** Phase B.3 soak completes 4 consecutive calendar weeks with ≥30
  C6 SELLs (~triple the current sample). At that volume, a per-symbol
  P&L breakdown becomes meaningful; if any single symbol clusters >50%
  of the loss, escalate to PARAM-TUNE on that symbol.
- **(b)** A single-week realized loss exceeds 1% of book (-$1.00 at
  $100). Loss of that size in a 5–7 day window invalidates the
  "below-noise-floor" KEEP rationale and triggers immediate triage.

If neither (a) nor (b) by end of B.3, recommend automatic KEEP roll-over
into the live-flip Track C evaluation.

## 6. Open follow-ups (NOT blocking B.3 entry)

- The `币安人生/USDT` symbol (parent §D) — scanner universe filter should
  bucket non-ASCII symbols separately; this is a scanner-side concern
  (`markets/crypto/scanner.py`), not C6. File against B.0.5 silent-audit
  follow-ups if it recurs.
- C6 scanner-pick filter starvation per 2026-05-18 audit lines 95–101 —
  recommend a separate scanner-tuning task post-B.3 to broaden picks
  that survive `correlation_guard + volume floor + $5 min size`.
  Out of scope for B.0/B.1.

## 7. Triage classification

**KEEP.** Re-evaluate after 4 weeks of B.3 soak; criteria in §5.
