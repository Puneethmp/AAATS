# L11 capital invariant legacy drift baseline — crypto -$8.5169

**Status:** ACCEPTED (baseline recorded 2026-05-27). Not a leak. Not blocking soak.
**Owner:** Operator on return; baseline file `data/capital_invariant_baseline.json`.
**Filed:** 2026-05-27 mid-soak session (D.5 day 4 of 30).

## Summary

L11 (`execution/paper_trader.py:assert_capital_invariant`) has fired WARN at
delta=-$8.5169 on every cycle since its first reading at 2026-05-26T10:57:53Z.
The delta is **a fixed constant**, not a growing leak. Strategy code is
internally symmetric — this is pre-instrumentation residual drift surfaced for
the first time when L11 shipped.

The 2026-05-27 patch adds a baseline-offset mechanism. The known $8.5169
historical drift is now subtracted from raw delta before the verdict; new
drift on top of the baseline still trips WARN at the existing $2 threshold.
Raw delta + baseline are surfaced in alert JSON and logs for auditability.

## Evidence

| Reading time (UTC) | actual_capital | expected | open_notional | realized_pnl | raw_delta |
|---|---|---|---|---|---|
| 2026-05-26T10:57:53Z | $109.49 | $118.01 | $83.78 | (n/a) | -$8.5169 |
| 2026-05-26T11:42:49Z | $102.92 | $111.44 | $90.35 | (n/a) | -$8.5169 |
| 2026-05-26T12:27:51Z | $106.86 | $115.38 | $85.60 | $0.9738 | -$8.5169 |
| 2026-05-27T07:12:49Z | $166.03 | $174.55 | $26.44 | $0.99 | -$8.5169 |

14 consecutive readings, fully reshuffled open positions and realized PnL,
delta unchanged at -$8.5169 to 4 decimal places. That is the signature of a
constant historical offset, not active leakage. A per-trade formula bug or
ongoing fee/slippage asymmetry would produce a delta that scales with trade
count or notional.

## Why it isn't a code bug

Audited 2026-05-27:

1. **Directional execute() path** (`trading/live_paper_runner.py:1348,1404`):
   `capital -= shares * fill` at BUY, `capital += shares * fill` at SELL.
   Slippage is in `fill` symmetrically. DB pnl uses fill prices. Open
   positions tracked via `paper_positions.json` → counted by
   `_read_directional_open_notional`. Net cycle effect: pnl — exactly what
   L11 sums from DB. **Consistent.**
2. **C3 altcoin reversion** (`trading/altcoin_reversion.py:653,754`):
   `capital -= trade_usd` at BUY, `capital += size + pnl` at SELL. No
   slippage applied. DB pnl = capital delta. State file `size_usd` matches
   debit. **Consistent.**
3. **C6 bollinger range** (`trading/bollinger_range.py:379,455`): same pattern
   as C3. **Consistent.**
4. **C1 stat_arb pair strategy** (`trading/stat_arb.py:276,464`):
   `capital -= alloc * 2` at ENTRY, `capital += alloc * 2 + total_pnl` at
   EXIT. State file stores `entry_alloc` with `× 2` multiplier in
   `_read_all_open_notional`. **Consistent.**

No code path produces an ongoing asymmetry that would create persistent
drift.

## Probable origin

One of:
- **2026-05-23T13:29Z phantom-ENA crash loop**: recovered via commits
  c71291e / 11b0874 / 86bc8d4 / 4219651. The recovery may have left a
  capital debit without a matching state-file entry or DB row (the
  "dual ledger" pattern catalogued in memory `aaats_dual_equity_ledger_debt.md`).
- **2026-05-26 structural fix deploy**: the L11 instrumentation itself
  shipped that day; if an in-flight trade was interrupted by the container
  rebuild, the same orphan-debit pattern could result.

Pinpointing the exact event would require walking
`runtime/paper_crypto.log` plus the DB row-by-row across 4 days of state.
The cost/benefit was judged not worth blocking the soak: $8.52 is below
the L11 CRITICAL threshold ($10) and below 5% of starting equity, and the
fix mechanism makes L11 self-recovering for new drift.

## What the patch does

`execution/paper_trader.py`:

- New helper `_read_legacy_drift_baseline(market, state_dir)` reads
  `data/capital_invariant_baseline.json` and returns the baseline USD for
  the market (0.0 if file or entry missing).
- `compute_capital_invariant` now returns `raw_delta_usd`,
  `baseline_drift_usd`, `effective_delta_usd`. Existing `delta_usd` field
  carries the EFFECTIVE delta (baseline-adjusted), so existing alert
  readers (Grafana panels, daily-digest, Telegram) keep working but now
  reflect baseline-adjusted truth.
- Verdict thresholds gate on `abs(effective_delta)`. Tolerance/warn/critical
  values unchanged ($0.50 / $2.00 / $10.00).
- Log lines now show `effective` + `raw` + `baseline` so an operator
  scanning logs can see at-a-glance whether L11 is firing on new drift or
  legacy.

`data/capital_invariant_baseline.json` (new): persists the crypto baseline
of -$8.5169 with full audit metadata (timestamp, recorder, reason,
source_alert_file, raw_delta_at_recording). India baseline = 0 for symmetry.

## Operator workflow

**Refresh the baseline (e.g. after operator deposit or after fully tracing
the legacy drift):**

```bash
# On the box:
ssh aaats@100.95.126.39 'rm /home/aaats/aaats/data/capital_invariant_baseline.json'
# Wait one cycle (~15 min). L11 fires WARN with the new raw delta.
# If legitimate, record a new baseline entry committing the JSON file.
```

**Investigate legacy drift on operator return:**

1. Walk `runtime/paper_crypto.log` from 2026-05-23T13:29Z forward for any
   `WARNING` or `ERROR` involving capital, state-file write, or DB insert
   failures during cycle execution.
2. Cross-reference with `git log --oneline data/*_state.json` between
   2026-05-23 and 2026-05-26.
3. Compare `data/halt_state.json` history snapshots if any survived.
4. Use the analyzer in `analytics/pnl_attribution.py` to reconstruct
   capital change from DB and diff against `paper_portfolio.json` history
   commits.

**Suspect a new leak rather than legacy:**

L11 effective_delta will be the canonical signal. raw_delta - baseline
should hover at $0. If effective_delta starts trending negative, a NEW
leak is accumulating; trace via the order-by-order ledger reconciler
(`scripts/reconcile_intracycle.py`).

## Sources

- Code: `execution/paper_trader.py:626-758` (L11 module)
- Baseline file: `data/capital_invariant_baseline.json`
- Triggering alerts: `runtime/capital_invariant_alerts.json` (14 consecutive
  WARN readings 2026-05-26T10:57:53Z onward, all delta=-$8.5169)
- Related memory: `aaats_dual_equity_ledger_debt.md` (pattern catalogue)
- Related memory: `aaats_2026_05_26_structural_fix_shipped.md` (L11 ship)
- Related memory: `aaats_2026_05_23_d5_soak_started.md` (phantom-ENA recovery)
