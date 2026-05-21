# Silent-strategy audit — Phase B.0.5 (2026-05-21)

**Window:** 2026-05-12 → 2026-05-21 (9 days, paper-crypto)
**Container:** `aaats-paper-crypto`, command `python trading/paper_loop.py --market crypto` (`deployment/docker-compose.yml:92`)
**Parent doc:** [`docs/decisions/2026-05-22_live_flip_rebuild_plan.md`](../decisions/2026-05-22_live_flip_rebuild_plan.md) §A (only C3+C6 fired), §D
**Companion memos:**
[`2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md`](2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md),
[`2026-05-21_strategy_c6_bollinger_range_diagnostic.md`](2026-05-21_strategy_c6_bollinger_range_diagnostic.md)

## Summary

Of the 12 strategies in the doctrine universe, only 2 fired in the 9-day
window (C3, C6 — see companion memos). This audit classifies the other 10
as either **deliberately-dormant** (gate logic honestly refused entry,
or strategy is intentionally disabled) or **regressed-silent** (the gate
should have allowed entry but a code/data path silently blocked it). Only
one strategy — **C1 stat_arb** — falls into regressed-silent, and it is
the highest-leverage near-term fix because a fully-loaded entry signal
(z=+4.74 per 2026-05-18 audit §P-extra 2) is sitting blocked behind a
data plumbing bug.

## Classification table

| Strategy | Classification | Evidence (file:line + doc) | Action |
|---|---|---|---|
| C1_stat_arb | **regressed-silent** | `trading/stat_arb.py:344` health gate requires `corr14d >= 0.80`; cached `corr14d=0.000` blocks BTC/ETH pair despite `z=+4.74` reaching at 2026-05-17T23:52Z (`docs/decisions/2026-05-18_strategy_activity_audit.md:118`, §P-extra 2 lines 144-154). `_rolling_correlation` at `trading/stat_arb.py:144-160` returns `None` on insufficient data — but the cached `0.000` value pre-dates that fix and poisons the 7-day cache (`_is_health_stale` at line 112-121 only refreshes on age, not on `0.0` sentinel). | **FIX (Phase B.1).** Invalidate `data/stat_arb_health.json` entry for `BTC/USDT_ETH/USDT` so the next cycle recomputes against the line-144 `None`-guarded path. One-line operator action (delete file or set `checked_at` to epoch). See §"Why C1 is highest-leverage" below. |
| C2_momentum_breakout | **deliberately-dormant** | Dispatch wired at `trading/live_paper_runner.py:1674-1677`. Gate at `trading/momentum_breakout.py:200-201`: `bull_reg = ema12 > ema26` AND `fg_ok = _fear_greed() >= FG_MIN` (40). Current regime per 2026-05-18 audit §P3 line 109 = BEAR_TREND, F&G=28 (Fear). Both gates honestly fail. Resolved per audit §P4 row C2 lines 119: "Strategy is alive and gating honestly. No action needed." | **NONE.** Will re-fire when regime flips to BULL_TREND + F&G crosses 40. |
| C5b_funding_arb | **deliberately-dormant** | Dispatch commented out at `trading/live_paper_runner.py:1666-1670` since 2026-05-15 with explicit comment "HALTED 2026-05-15: see docs/known_issues/2026-05-15_c5b_halt.md". Reason: BUY-records-per-leg vs SELL-records-round-trip schema delta would fire share-equality WARN at $25/close (`docs/known_issues/2026-05-15_c5b_halt.md:12-23`). | **NONE until unified-ledger Q1–Q4 resolved.** Re-enable per `docs/known_issues/2026-05-15_c5b_halt.md:26-44` checklist. |
| N1_stat_arb_india (HDFCBANK/ICICIBANK) | **deliberately-dormant** | Pair defined at `trading/stat_arb.py:58` with `market="india"`. The container runs `--market crypto` (`deployment/docker-compose.yml:92`); the `run_stat_arb_india` entry point at `trading/stat_arb.py:478` is never invoked from the crypto cycle. Comment at `trading/stat_arb.py:57`: "India dormant until week 7+ (NSE module not live yet)." | **NONE.** Out of scope for this plan per parent doc §"What this plan does NOT cover" (NSE strategies). |
| N2_overnight_gap_fade | **deliberately-dormant** | No source file. `grep -r "N2_" trading/` returns zero hits; the strategy is a design-time label in `docs/operator/aaats_strategy_universe.md:66` only ("See original memory for full N2-N7 definitions; not material to current Track B work since NSE side is out of scope"). | **NONE.** Design label, not deployed code. |
| N3_opening_drive | **deliberately-dormant** | No source file. Same evidence as N2: design label only at `docs/operator/aaats_strategy_universe.md:66`. | **NONE.** |
| N4_vwap_reversion | **deliberately-dormant** | No source file. Same evidence as N2: design label only at `docs/operator/aaats_strategy_universe.md:66`. | **NONE.** |
| N5_event_drift | **deliberately-dormant** | No source file. Same evidence as N2: design label only at `docs/operator/aaats_strategy_universe.md:66`. | **NONE.** |
| N6_index_rotation | **deliberately-dormant** | No source file. Same evidence as N2: design label only at `docs/operator/aaats_strategy_universe.md:66`. | **NONE.** |
| N7_earnings_drift | **deliberately-dormant** | No source file. Same evidence as N2: design label only at `docs/operator/aaats_strategy_universe.md:66`. | **NONE.** |

## Tally

- **regressed-silent:** 1 (C1)
- **deliberately-dormant (gate-honest):** 2 (C2, C5b)
- **deliberately-dormant (market not loaded):** 1 (N1)
- **deliberately-dormant (no source file exists):** 6 (N2–N7)
- **Total accounted:** 10 silent strategies + 2 firing = 12 doctrine-universe coverage

This confirms parent doc §"Top-line" finding: the 12-strategy universe is
nominal, not operational. The Track B triage scope is genuinely 1–2
strategies (C3 PARAM-TUNE + C6 KEEP) plus the C1 plumbing fix.

## Why C1 corr14d=0 is the highest-leverage fix

C1 is the only **regressed-silent** classification in the 9-day window,
and the leverage is high because:

1. **The signal is loaded and stale-blocked, not absent.** Per 2026-05-18
   audit §P-extra 2 (lines 144–154): `z=+4.74` was reached at
   `2026-05-17T23:52Z` — well past the entry threshold `entry_z=1.8`
   (`trading/stat_arb.py:56`). A typical BTC/ETH 14-day rolling
   correlation is ~0.7–0.9, not 0.000. The cached zero is a stale
   poisoned value from before the `None`-guard fix at
   `trading/stat_arb.py:144-160`.
2. **The fix is a file deletion, not a code change.** Removing
   `data/stat_arb_health.json` (or zeroing its `checked_at` field) forces
   the next cycle through `_is_health_stale` (`trading/stat_arb.py:112-121`)
   into a fresh recompute against the corrected None-guarded path.
   The fix is well under one line of code and zero deployment risk.
3. **C1 is structurally market-neutral.** Long BTC + Short ETH (or
   vice-versa) has no directional exposure to the macro regime that
   blew up C3 on 2026-05-18. Adding a market-neutral leg to a paper book
   currently 90% concentrated in directional alt-reversion lowers the
   correlation of equity-curve P&L.
4. **It changes the soak math for Track B.3.** With C1 active, B.3's
   4-week soak measures a 3-strategy stack (C3 tuned + C6 KEEP + C1
   stat-arb), which is materially closer to the doctrine intent than the
   2-strategy stack the plan would otherwise soak.
5. **The fix is gated against the same kill-switch architecture as C3/C6**
   already (`apply_kill_switch_gate` at the runner level — though
   `trading/stat_arb.py` does not currently call it; pre-deployment
   review should add that call site for parity with
   `trading/altcoin_reversion.py:521-525` and
   `trading/bollinger_range.py:336-346`).

**Recommended sequencing:** wire C1 stat-arb fix as a Phase B.1 prereq to
B.2, not as a Phase B.2 sweep target — there is nothing to sweep, the
cache is just poisoned. Do C1 first, then start the C3 BTC.D sweep.

## What this audit does NOT cover

- **C4_new_listing and C5a_directional_perps** — design-doctrine labels;
  source files never existed per 2026-05-18 audit §P4 row C4/C5a (lines
  121–122: "module does not exist in /app/trading/"). Treated as out of
  scope (no code = nothing to classify).
- **Scanner-pick filter starvation for C6** — covered in the C6 memo
  §3; not a silent-strategy issue, a pipeline-composition issue.
- **`halt_state.json` india=true and us=true** — both India and US
  HALTed at the kill-switch layer per parent doc §E and the 2026-05-21
  reconcile snapshot. Out of scope for this audit (crypto-only window).

## Triage table for Phase B.1

| Strategy | Verdict | Source memo |
|---|---|---|
| C1_stat_arb | FIX (cache invalidation, prereq for B.2) | this audit + 2026-05-18 audit §P-extra 2 |
| C2_momentum_breakout | KEEP (gate-honest) | this audit + 2026-05-18 audit §P4 row C2 |
| C3_altcoin_reversion | PARAM-TUNE | companion memo |
| C5b_funding_arb | HALT (existing) | `docs/known_issues/2026-05-15_c5b_halt.md` |
| C6_bollinger_range | KEEP (insufficient data) | companion memo |
| N1–N7 | OUT OF SCOPE | this audit |
