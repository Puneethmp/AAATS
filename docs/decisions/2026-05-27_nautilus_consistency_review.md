# NautilusTrader port — consistency review vs B.1.5 findings

**Status:** REVIEW (read-only assessment). No runtime impact, no NT install, no code ported.
**Authored:** 2026-05-27 (Claude Code session, D.5 soak day 4).
**Reviews:** [`2026-05-27_c3_nautilus_port_and_graduation_gate.md`](2026-05-27_c3_nautilus_port_and_graduation_gate.md) (the B.1.6 C3 pilot plan) and [`2026-05-27_nt_final_extraction_for_success.md`](2026-05-27_nt_final_extraction_for_success.md) (the capability inventory + adoption roadmap), both Cowork-authored 2026-05-27.
**Checks against:** [`docs/specs/b15_backtest_harness.md`](../specs/b15_backtest_harness.md) (Phases 3.5/4/5), [`2026-05-27_b15_doctrine_proposal.md`](2026-05-27_b15_doctrine_proposal.md), [`docs/operator/aaats_locked_doctrine_2026_05_14.md`](../operator/aaats_locked_doctrine_2026_05_14.md), `feedback_regime_filtering_at_allocator.md`.

---

## Verdict: **PARTIAL**

The NautilusTrader port plan is **sound on execution modeling and correctly scoped to C3** — it closes the single biggest B.1.5 gap (the homegrown harness applies symmetric slippage with zero fees and cannot model whether C3's limit entries actually fill). It correctly treats C1 and C6 as dead and does not port them. It does not touch the live runner, the box, or the soak, and it explicitly supersedes nothing.

But it is **PARTIAL, not SOUND, because it does not address the regime-dependence finding.** B.1.5 Phase 4 established that C3 is WINDOW-DEPENDENT — DEAD in 1 of 5 historical 60d windows (W2, a trending regime) — and Phase 5 established that this cannot be fixed inside the strategy; regime-awareness must live at the allocator. Porting C3 to a realistic-execution engine fixes *how fills are costed*; it does nothing about *which regime the market is in*. Worse, the proposed graduation gate computes a single blended out-of-sample number, which can **mask** regime-dependence: a strategy that nets +$12 across four windows and −$1 in a trending window passes "net PnL > 0" while still carrying the ~20%-of-windows-lose risk B.1.5 quantified. The plan conflates "survives realistic execution" with "robust strategy." Both are required for live-flip; the plan delivers only the first and is silent on the second.

This is a closeable gap, not a contradiction. Close it (see "Gaps to close") and the plan becomes SOUND.

---

## Q1 — Does the NT fill/slippage model meet or exceed the B.1.5 harness assumptions?

**YES.**

- B.1.5 harness: symmetric `slippage_bps` applied to a bar-close fill, **zero fees** ([`tools/backtest/c3_replay.py:126-128`](../../tools/backtest/c3_replay.py#L126-L128), cited in port doc line 17). Break-even was interpolated from a 7-point symmetric-slippage sweep ([b15_backtest_harness.md:360](../specs/b15_backtest_harness.md#L360)).
- NT plan: `MakerTakerFeeModel` (Binance VIP-0, 10 bps spot maker/taker) + `FillModel` (probabilistic limit/stop fill) + 2–15 bps market impact (port doc lines 134–142; capability verified hands-on in nt_final lines 36–43).
- NT's model is strictly more conservative *and* more realistic: it charges the 10 bps fee the harness omitted entirely, and it models the actual live-viability mechanism — whether a resting maker limit order fills, vs. paying impact by crossing the spread (nt_final line 43, port doc line 142). C3's break-even is 22.79 bps/side ([b15_backtest_harness.md:319](../specs/b15_backtest_harness.md#L319)); a 10 bps fee + impact lands right at that line, which is exactly the coin-flip the plan acknowledges (port doc line 162). The NT model meets-or-exceeds the harness and, more importantly, tests the right question.

## Q2 — Does the graduation gate use the B.1.5 break-even as its threshold?

**YES, operationalized — with a traceability note.**

- The gate (port doc lines 150–160) is generic: G1 net PnL > 0 OOS, G2 Sharpe ≥ 1.0, G3 maxDD ≤ 20%, G4 ≥ 30 trades, G5 PF ≥ 1.3, G6 OOS/IS degradation ≥ 0.5×, G7 maker-fill robustness. It does **not** hard-code "22.79 bps."
- This is the *correct* design, not a weakness: G1 ("net PnL > 0 after realistic fees + impact on OOS") is the operational equivalent of "clears break-even under honest cost." Re-deriving net PnL under NT's real model supersedes the harness's 22.79 bps estimate (itself a crude-model artifact). Hard-coding 22.79 would be wrong; G1 + the realistic cost model is right. The doc explicitly connects gate to break-even: "C3's OOS break-even is right at the cost line, so G1/G2 are live coin-flips" (port doc line 162).
- **Note (not a blocker):** the gate doc should cross-reference the 22.79 bps figure and the Phase 4 walk-forward JSON so the NT OOS result is read against the known naive-model number rather than in isolation. nt_final already references `c3_walkforward_6mo_2026_05_27.json` (line 222); the gate spec should too.

## Q3 — Does the plan correctly treat C1 and C6 as DEAD?

**YES.**

- Port doc line 12 carries the exact B.1.5 verdicts (C1 BE 2.83 bps DEAD; C6 unprofitable at zero cost DEAD; C3 MARGINAL BE 22.79). Line 29: "Not porting C1 or C6. Your own data says they are dead at any cost level — porting them is wasted effort."
- nt_final line 20 concurs ("C1/C6 dead"). C3 is the sole port target.
- Consistent with the doctrine proposal's verdict table and with the locked doctrine, which already defers C1 to "year 2+, portfolio > $1k" for separate (order-size) reasons ([aaats_locked_doctrine_2026_05_14.md:80](../operator/aaats_locked_doctrine_2026_05_14.md#L80)).

## Q4 — Does the plan address window-dependence (Phase 4) + regime-gate ineffectiveness (Phase 5)?

**NO — this is the gap.**

- The plan addresses the *single-window / no-OOS* caveat well: 6-month fetch, 4mo in-sample + 2mo OOS, optional walk-forward, and G6 to catch overfit (port doc lines 124–128, 157).
- But neither doc mentions the **regime-dependence** finding: C3 DEAD in W2 (trending regime) at zero cost ([b15_backtest_harness.md:398-400](../specs/b15_backtest_harness.md#L398)), the GATE-INEFFECTIVE Phase 5 result ([b15_backtest_harness.md:481](../specs/b15_backtest_harness.md#L481)), or the established rule that regime-awareness belongs at the allocator, not inside the strategy (`feedback_regime_filtering_at_allocator.md`; [b15_backtest_harness.md:498](../specs/b15_backtest_harness.md#L498)).
- Better execution does not fix regime-dependence: a W2-equivalent trending stretch loses money for a mean-reversion strategy regardless of whether fills are maker or taker. The graduation gate's blended-OOS G1 can even **mask** this — averaging a losing trending window into four winning windows still nets positive and passes. The plan treats "survives realistic execution" and "robust strategy" as the same thing; B.1.5 proved they are not.

## Q5 — Consistent with locked doctrine + the existing roadmap?

**YES, with two minor flags (neither requires adjudication).**

- **Strongly aligned** with the locked doctrine's own C3 plan: "C3 → C5a perpetual mean reversion **at maker fees** (alpha sleeve, 30%)" ([aaats_locked_doctrine_2026_05_14.md:75](../operator/aaats_locked_doctrine_2026_05_14.md#L75)). Testing C3 under maker-fee/limit execution is precisely the doctrine's intended C3 path.
- **No LLM in the execution path** (NT is a deterministic event engine; C3 is pure math) and **direct exchange adapters** (NT's adapters are direct, not OpenAlgo) — consistent with the locked execution-architecture stance.
- **No change to capital sizing** — the docs don't touch the $100 initial-live / $25 injection-baseline schedule.
- **Scoped as research tool, not migration:** "Not running NT as a separate live bot… the box keeps running AAATS" (port line 28); "Production deployment stays in the AAATS runtime unless/until a later decision" (port line 31); "Supersedes nothing" (port line 6). It does not unilaterally re-open any settled decision.
- **Flag 1 (minor):** nt_final item #6 advertises NT's Binance/Bybit/IB adapters and multi-venue capability (lines 125–138). This brushes the doctrine's "LIKELY NEVER: multi-venue routing" line ([aaats_locked_doctrine_2026_05_14.md:84](../operator/aaats_locked_doctrine_2026_05_14.md#L84)). The doc frames it as P2 "interface borrow now, implementation decision later… even if you don't use NT's adapter in production" — so it does not commit to multi-venue, but the operator should note the tension.
- **Flag 2 (minor):** nt_final item #5 (research→live parity via `live.node`) is floated as "the destination" (P2/P3). If pursued, it would eventually touch the locked broker-adapter/live-loop architecture — but it is explicitly deferred ("don't rebuild the live path until you have a graduated edge"). Not a near-term conflict; flagged so the eventual decision is conscious.

---

## Do the two docs contradict each other?

**No.** They are complementary: `c3_nautilus_port_and_graduation_gate.md` is the C3 pilot plan; `nt_final_extraction_for_success.md` is the capability inventory + prioritized P0–P4 roadmap that the pilot is the first instance of. nt_final explicitly frames itself as the "what to take and why," with the other two docs being "the plan to take it" (nt_final line 6). The C3-only scope, the C1/C6-dead stance, and the FillModel/FeeModel P0 priority are identical across both.

---

## Gaps to close before the NT plan becomes the roadmap

1. **Add a per-window (regime) breakdown to the graduation analysis — do not graduate on a blended OOS number alone.** Either add a gate criterion that no individual 60d sub-window is DEAD (net-negative), or explicitly document that the NT gate validates *execution viability only* and that *regime-robustness is a separate, allocator-level requirement* per Phase 5. Without this, the gate can pass a strategy that still loses in ~20% of 60d windows.
2. **Acknowledge Phase 4 + Phase 5 explicitly in the port doc.** State that NT-validated execution and allocator-level regime weighting are *both* prerequisites for live-flip, not just the former. Cite `feedback_regime_filtering_at_allocator.md`.
3. **Cross-reference the 22.79 bps break-even + the walk-forward JSON in `graduation_gate.md`** so the NT OOS net-PnL is read against the known naive-model number, not in isolation.
4. **(Operator awareness, not a code change):** the multi-venue adapter mention (nt_final #6) and the NT-live-deployment vision (nt_final #5) each touch a settled doctrine line. Keep them flagged as deferred until an explicit operator decision; don't let "borrow the interface" drift into "adopt the platform" without one.

---

## What B.1.5 already proved (so the NT work does not redo it)

- **C3 is MARGINAL and WINDOW-DEPENDENT.** Break-even 22.79 bps/side on a single window; across 5 overlapping 60d windows, 4 MARGINAL / 1 DEAD (W2 trending regime). The soak window (W5) is the *best* window, not representative — expect a ~30–50% haircut on soak Sharpe for regime variance.
- **C1 and C6 are dead.** C1 break-even 2.83 bps (below Binance perp maker); C6 unprofitable at zero cost. Not worth porting. NT effort is C3-only.
- **The break-evens are known numbers** (C1 2.83 / C3 22.79 / C6 <0 bps per side). The NT port should *re-derive C3's under a realistic model*, not re-discover that C1/C6 are dead.
- **Regime-gating must be allocator-level.** A single-strategy regime gate was tested (Phase 5) and is GATE-INEFFECTIVE — it over-filters good windows. Regime-awareness belongs in portfolio capital-weighting, not in C3's entry hook. The NT port does not change this; it is orthogonal.

---

## Process notes

- **No soak-freeze violation.** Both docs are explicitly workstation/research-only and leave the box and live runner untouched (port line 3, 28; nt_final line 3). This review confirms no proposed action touches `trading/`, `execution/`, `risk/`, `strategies/`, the box, or any container.
- **Cross-surface install note.** nt_final claims NautilusTrader was "installed and introspected hands-on" (lines 5, 204–213). That was in the **Cowork sandbox** — NautilusTrader is **not** present in the Claude Code workstation venv (verified: `import nautilus_trader` → ModuleNotFoundError). The verification appendix is credible but reproduces only in the Cowork environment as written; a B.1.6 build from Claude Code would need its own install step (per the doc's own "next build step" note, line 204).
- The strategic A/B/C/D decision from the B.1.5 doctrine proposal remains deferred to the operator at soak-end (~2026-06-22). This NT thread is best read as a concrete elaboration of that proposal's **Option D-adjacent** direction (validate-then-deploy with realistic execution), and shares Option D's blind spot if the regime layer is not added.
