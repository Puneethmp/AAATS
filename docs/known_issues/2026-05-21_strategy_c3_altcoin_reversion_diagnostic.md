# C3 Altcoin Reversion — diagnostic memo (2026-05-21)

**Strategy ID:** C3_altcoin_reversion
**Window:** 2026-05-12 → 2026-05-21 (9 days, paper-crypto)
**Status — Verdict:** PARAM-TUNE (contingent HALT if tune fails post-soak)
**Parent doc:** [`docs/decisions/2026-05-22_live_flip_rebuild_plan.md`](../decisions/2026-05-22_live_flip_rebuild_plan.md) §A–§D

## Summary

C3 is the source of ~98% of the 9-day realized loss ($-5.63 of the $-5.76
realized total per parent §A). The loss is concentrated in 5 of the 32
traded symbols (78% of $-5.63 in OP/ARB/PUMP/FET/LUNC, parent §B), AND the
strategy's own design intent (skip entries when BTC dominance is rising
fast — module docstring at `trading/altcoin_reversion.py:11`) is *defined
but unwired* in `_entry_allowed`. Wire the BTC.D filter and re-soak before
deciding HALT vs KEEP.

## 1. Evidence: design intent vs runtime behaviour

1. **Docstring asserts BTC.D-rising filter** —
   `trading/altcoin_reversion.py:10-11`:
   ```
   Skips:  BTC dominance rising fast (>0.8%/cycle) — alt season over
   ```
2. **Constant exists** — `trading/altcoin_reversion.py:77`:
   ```python
   BTC_DOM_FAST_RISE = 0.008    # skip if BTC dominance rising >0.8% since last cycle
   ```
3. **`_entry_allowed` ignores it** — `trading/altcoin_reversion.py:314-330`.
   The function checks BTC RSI ≥ 35 (line 320-322) and regime != BEAR (line
   326-328), then returns True. There is no read of `BTC_DOM_FAST_RISE` and
   no `btc_dom` argument or `from foundation.btc_dominance import …` import
   anywhere in the module. `grep -n BTC_DOM_FAST_RISE trading/altcoin_reversion.py`
   returns exactly one hit — the constant declaration. Runtime confirmation:
   the live runner does fetch `btc_dom` and applies it as a global alt-BUY
   filter at `trading/live_paper_runner.py:1625-1632`, but the BTC.D-rising
   logic per parent strategy spec is C3-specific and never executed.

This is the load-bearing bug. The 2026-05-18 blowup day (parent §C: 9 SELLs
all losers, $-2.81 single-day, >2.5× any other day) is the externally
visible symptom of "alt season over, but C3 still entering."

## 2. Symbol concentration of the C3 loss

Per parent §B (sorted worst-first):

| Symbol | Trades | SELLs | PnL (USD) | WR |
|---|---:|---:|---:|---:|
| OP/USDT | 2 | 1 | -1.296 | 0% |
| ARB/USDT | 2 | 1 | -1.063 | 0% |
| PUMP/USDT | 2 | 1 | -0.782 | 0% |
| FET/USDT | 4 | 2 | -0.717 | 0% |
| LUNC/USDT | 6 | 3 | -0.560 | 0% |
| **Top-5 subtotal** | **16** | **8** | **-4.418** | **0%** |
| All other 27 C3 symbols | 76 | 36 | -1.216 | ~32% |
| **C3 total** | **92** | **44** | **-5.634** | **27%** |

**Symbol-level halt math (residual P&L if top-5 are denylisted within C3):**

- C3 total realized over 9d: $-5.634 (44 SELLs, 27% WR)
- Top-5 contribution: $-4.418 in 8 SELLs at 0% WR
- **Residual (27 symbols, 36 SELLs): $-1.216 over 9 days**
- Residual EV per SELL: $-1.216 / 36 ≈ **$-0.0338 / trade**
- Residual WR: ~33% (12W / 36 SELLs, parity with 36/44 WR-comparable
  per-strategy ratio adjusted for the 0/8 top-5 record)
- Residual 9-day P&L as % of $100 book: **-1.22%**

Translation: pulling the top-5 losers turns C3 from a -$5.63/9d disaster
into a -$1.22/9d slow bleed. Still negative-EV but inside noise; the
extracted-loss component is symbol-specific, not strategy-specific.

## 3. Win/loss magnitude asymmetry

Per parent §A:
- avgW = +$0.253, avgL = -$0.279 (all-9d)
- avgW = +$0.253, avgL = -$0.344 (7d window — losses *grew* in recent
  window, consistent with BTC-led rally hypothesis)
- Best trade +$1.044, worst -$1.296

Losers are 10–36% larger in magnitude than winners. Combined with 27% WR,
the EV math is structurally negative. Two paths to make EV positive:
either lift WR (~55% needed to break even at current magnitudes) or
shrink avgL (tighten Z_HARD_STOP — currently -2.6 per
`trading/altcoin_reversion.py:73`).

## 4. Why this is PARAM-TUNE not HALT (yet)

1. The BTC.D-rising filter is the strategy author's own listed safeguard
   (`trading/altcoin_reversion.py:10-11`); wiring it is a 1–3 line patch,
   not new design. A tune-then-soak attempt is cheap.
2. The loss concentration in 5 symbols (78% in 16% of the universe)
   suggests symbol-specific blowup risk rather than strategy-wide regime
   misfit. A symbol-level denylist + BTC.D filter together address both
   the systemic 2026-05-18-style event AND the per-coin LUNC→LUNC
   re-entry pattern that the 2026-05-13 cooldown was supposed to fix
   (`trading/altcoin_reversion.py:97`).
3. C3 produces 92/102 = 90% of paper-crypto trade volume over the 9-day
   window (parent §A). HALTing it without a replacement leaves the
   2-strategy stack down to C6 (10 trades / 9d). Phase B.3's 4-week soak
   needs trade-density to be informative; C3-only-halted ≠ a stack to
   soak.

## 5. Recommended next steps (PARAM-TUNE path, in order)

1. **Wire the BTC.D-rising filter (one-line patch, blocking).**
   Pass `btc_dom_delta` (or read it from the same source the runner uses at
   `trading/live_paper_runner.py:1625`) into `_entry_allowed`. Concretely:
   ```python
   # trading/altcoin_reversion.py:_entry_allowed (~line 314)
   def _entry_allowed(btc_df, regime, btc_dom_delta: float | None = None) -> bool:
       if btc_dom_delta is not None and btc_dom_delta > BTC_DOM_FAST_RISE:
           log.debug("[c3] BTC.D rising %.4f > %.4f — skip entry",
                     btc_dom_delta, BTC_DOM_FAST_RISE)
           return False
       # … existing RSI + regime checks unchanged …
   ```
   Caller change in `run_altcoin_reversion_crypto` (~line 459-463) to compute
   `btc_dom_delta` from BTC.D cache and pass it through. The caller already
   has the runner-side btc_dom value (live_paper_runner.py:1625) — surface
   it as a parameter rather than re-fetching.
2. **Apply symbol denylist within C3 for OP/ARB/PUMP/FET/LUNC.** Smallest
   useful diff: skip these in the per-cycle universe loop at
   `trading/altcoin_reversion.py:487` until a separate per-symbol
   re-entry decision is made. Justification: 0/8 SELL WR on these is not
   a coin-fundamentals call; it's a 9-day refusal-to-mean-revert pattern
   in five names. Denylist is a temporary safety guard, not a strategy
   change.
3. **Tighten `Z_HARD_STOP` from -2.6 → -2.2** (one-line change at
   `trading/altcoin_reversion.py:73`). avgL of -$0.344 (7d window) divided
   by typical position size of $10 (POSITION_USD, line 57) implies stops
   are firing at ~-3.4% on average. -2.2 z would cap losses tighter; the
   trade-off is lower WR (more stops cut before mean reversion). Sweep
   range −2.0 → −2.6 in Phase B.2.
4. **Re-soak in B.3 for 4 weeks.** Acceptance criterion: positive equity
   curve, no single-week loss >5%. If after 4 weeks C3 still negative,
   escalate to HALT per parent §B.1.

## 6. What is NOT recommended

- **Full C3 HALT today** — C3 carries the trade-density of the paper book;
  HALTing without replacement collapses the soak signal. Tune-then-soak
  is cheaper.
- **Per-symbol cooldown tightening** — already at 24h
  (`trading/altcoin_reversion.py:97`); 2026-05-13 v2 work already
  addressed the LUNC→LUNC re-entry case. Further tightening doesn't
  address the 2026-05-18 market-event pattern.
- **Killing the scanner-driven universe** — diversification across 32
  symbols is good; the loss isn't from coverage breadth, it's from
  systemic regime exposure (BTC rally) plus 5 outlier names.

## 7. Open questions

- The 2026-05-18 blowup correlates 9/9 losers across the C3 universe
  (parent §D). Was this a single BTC.D-rising window that the unwired
  filter would have caught, or a different macro factor? Recommend Phase
  B.2 backtest the BTC.D filter against the 2026-05-18 14:00–20:00 UTC
  window before B.3 deployment.
- C3 trade rows tag `regime=RANGE_OR_BULL` (per audit
  `docs/decisions/2026-05-18_strategy_activity_audit.md:111-112`) — a
  literal string, not the live BTC regime. The runner-side
  `apply_kill_switch_gate` at `trading/live_paper_runner.py:521-525`
  references the live regime; verify the gate path actually consumes
  C3's regime intent.

## 8. Triage classification

**PARAM-TUNE.** Step 1 (BTC.D wire) is blocking; steps 2–3 are part of
the same Phase B.2 sweep. Phase B.3 4-week soak decides KEEP vs HALT.
