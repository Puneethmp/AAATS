# B.1.5 doctrine proposal — strategy retirement + regime-aware allocator

**Authored:** 2026-05-27 (mid-soak, autonomous Claude Code session)
**Status:** OPERATOR DECISION REQUIRED on return from D.5 soak (~2026-06-22)
**Decision scope:** Which of C1, C3, C6 stay in the live-flip path, and at what architectural layer regime-awareness lives.

---

## Executive summary

**Operator decision needed by ~2026-06-22 (D.5 soak end).** B.1.5 harness validated three strategies across 6 months of Binance 1h history. Verdicts: **C1 and C6 are DEAD at any realistic execution cost** (C1 break-even 2.83 bps/side, below Binance perp maker; C6 unprofitable at zero cost). **C3 is MARGINAL with window-dependent risk** (4/5 historical 60d windows MARGINAL, 1/5 DEAD) and a hard ceiling on in-strategy improvement (Phase 5 single-strategy regime gate is GATE-INEFFECTIVE; max in-strategy upside is ~+$1.18/60d, less than the over-filter cost it imposes on MARGINAL windows).

Four options below; **recommendation is B + D combined**: retire C1+C6 from live now to clean the soak signal (B), and queue allocator-level regime weighting as the next major sprint post-decision (D). Reasoning: B is high-leverage low-effort, D addresses the structural finding at the right architectural layer, A loses 6 weeks of operator time, C throws away usable D.5 stability data. The Phase 3.5 framing ("keep C3 with execution discipline focus, build C3-class supplements") survives intact.

---

## B.1.5 harness verdicts

Six months of 1h Binance OHLCV (2025-11-28 → 2026-05-27), C3 universe + C1 BTC/ETH pair + C6 BTC/ETH/SOL.

| Strategy | Break-even (bps/side) | Phase 4 window verdict | Phase 5 gating | In-strategy upside ceiling | Live-flip status |
|---|---:|---|---|---:|---|
| **C1** stat_arb (BTC/ETH) | **2.83** | not re-tested (already DEAD) | n/a | $0 — cannot pay any realistic fee | **ARCHITECTURALLY DEAD** |
| **C3** altcoin_reversion | **22.79** (W5: 29.6, worst MARG W3: 10.8) | **WINDOW-DEPENDENT** (4/5 MARG, 1/5 DEAD) | **GATE-INEFFECTIVE** (W3 turns DEAD, W4/W5 degrade ~66%) | ~$1.18 / 60d | **NOT READY** — regime risk |
| **C6** bollinger_range | **<0** | not re-tested (already DEAD) | n/a | $0 — unprofitable at zero cost | **ARCHITECTURALLY DEAD** |

**Read this as:** C1 needs near-free execution to break even (Binance perp maker is 2 bps; C1 dies on its first trade in live). C6 has no positive zone on this 60d window — there is no cost low enough to make it profitable. C3 has a real edge in 4 of 5 historical 60d periods, but a clean separation of the bad window via simple in-strategy thresholds is mathematically not possible at the bot's live observation horizon.

The W5 (most-recent 60d) window overlaps the live D.5 soak — soak PnL is therefore tracking the **best-case** historical window, not the cross-window mean. Don't extrapolate soak Sharpe directly; apply a ~30-50% haircut for regime variance.

---

## Strategic options

### A. Status quo soak + minimal action

Keep all three strategies running through D.5. Make the strategy-retention decision at soak end without changes during the soak.

**Pros:** Zero risk to soak data continuity. No mid-soak state changes. Preserves the stability-test surface (watchdog, halt machinery, alert paths). Smallest reversibility cost — option to switch to B/C/D at soak-end is still open.

**Cons:** Produces no new information beyond what B.1.5 already established. The soak PnL signal is biased by C1+C6 contributions (both DEAD, both burning notional). Operator returns to make the same decision under no better data — except the soak signal is dirtier than it could be. The 6 weeks of operator-away time produces a marginal datum for a question that's already answered.

**When this is the right call:** if there is any concern that retiring C1+C6 mid-soak would destabilize the watchdog or halt machinery in ways B.1.5 hasn't anticipated. Default to A only if the operational risk of B exceeds the signal-cleanliness benefit.

### B. Retire C1+C6 from live now; keep C3 with execution discipline focus

Halt C1 and C6 immediately via the persistent strategy-halt mechanism (`risk/strategy_halt.halt_strategy`). C3 continues running through the remainder of the soak. Focus any C3 review during the soak on the slippage-fragility finding (live path applies zero slippage per `[[aaats-c3-slippage-fragility]]`); document a TWAP / limit-order execution discipline spec for post-decision implementation.

**Pros:** Soak PnL becomes a cleaner signal for C3 alone — the metric the operator actually wants. Aligns the live posture with B.1.5's verdicts. Halt mechanism is well-tested (already used for the C1 halt-and-resume cycle on 2026-05-26). No code changes required; pure operator action.

**Cons:** Changes mid-soak state — reduces the "ran 30d without intervention" claim for the doctrine's D.5 exit gate. (Mitigation: a strategy halt is not a code change; the soak continues running the *system* untouched, just with C1+C6 not entering new positions.) Slight reduction in active-strategy diversity during the soak.

### C. Retire all three; rebuild C3-class supplements

Halt the entire crypto stack. Treat B.1.5 as having proven all three current strategies live-unready. Start the next sprint with new mean-reversion strategies designed against B.1.5's verdicts (e.g., alt-vs-alt pairs, longer-horizon reversion, regime-aware sizing built in from the start).

**Pros:** Cleanest reset. Removes architectural debt of carrying two known-DEAD strategies. Forces the doctrine's "build supplements before live-flip" framing into action.

**Cons:** Zero crypto trading activity for 1-2 months while supplements are designed and back-tested. Loses the soak's stability-test continuity (the part that *was* working — watchdog, halt, alerts). Throws away usable data on the parts of the system that aren't in question. The decision is too maximal for a question that's surgically about C1+C6.

**When this is the right call:** only if the operator wants a complete strategic reset for non-B.1.5 reasons (e.g., shift to perp-only, change exchange, refactor the strategy ABI).

### D. Build allocator-level regime weighting

Keep all three strategies running but add a portfolio-level regime classifier that down-weights C3 in trending regimes. Allows the in-strategy verdicts to stay as-is while addressing the window-dependence at the right architectural layer (per [[feedback-regime-filtering-at-allocator]] — Phase 5 established that single-strategy regime gating is structurally fragile; smoother, slower, portfolio-level regime signals are more robust).

**Pros:** Addresses the structural finding from Phase 5. The 60d-aggregate trend_strength feature *does* cleanly separate W2 from MARGINAL windows (z=+5.43); the failure mode in Phase 5 was the per-bar trailing horizon, not the regime signal itself. A portfolio-level signal operates at a slower cadence and is far less noise-sensitive. Doesn't require modifying any strategy file.

**Cons:** Requires net-new work — ML or rule-based regime classifier + allocator refactor to support per-strategy regime weights. 1-2 sprints minimum. Adds a new failure surface (the regime classifier itself) and a new piece of state to monitor. Doesn't help C1+C6 (which are dead independent of regime).

---

## Recommendation

**B + D combined.**

1. **B (now, mid-soak):** Halt C1 and C6 via `kill.py` strategy-halt during the remaining ~25 days of soak. The soak then measures what the operator actually cares about — C3's behavior in a near-best-case window. No code change; this is the kill-switch behaving as designed.

2. **D (post-decision, next sprint):** Begin allocator-level regime weighting as the next major sprint after operator return. Design constraints: regime signal computed at portfolio cadence (not per-bar); features drawn from the Phase 5 fingerprint set (`trend_strength`, `max_drawdown_pct`, `directional_pct` on BTC); applied as a multiplicative scalar on C3's capital share, not as an entry gate inside C3.

**Why not A:** A produces no new information for 25 days, and the soak signal stays dirty. Operator returns to make the same decision under the same data.

**Why not C:** C throws away the parts of the system that are working (stability infra, halt mechanism, watchdog) in service of a problem that's surgically about C1+C6. Too maximal.

**Why not D alone:** D is a 1-2 sprint piece of work. Doing only D leaves C1+C6 contributing dirty signal to the soak in the meantime. B is the cheap action that improves the data quality now; D is the structural fix that the data quality will be used to validate.

**Reversibility:** B is fully reversible via `kill.py` reset. D is a new module that can be feature-flagged off if the regime signal disappoints. Neither makes the decision harder to revisit at soak-end + 30d.

---

## What this proposal does NOT change

- **Soak continues regardless of decision.** D.5 watchdog, halt, alerts, autopush, L11 invariant, daily digests — all unchanged. The anomaly-window counter continues toward day-30 (ETA 2026-06-22).
- **No code modified by this memo.** Trading, execution, risk, strategies code is untouched. The memo is purely a decision artifact. Implementation of whichever option lands happens in a follow-up sprint **after operator approval**, not as a side effect of this document.
- **L11 capital invariant baseline holds.** `effective_delta_usd ≈ 0` anchor since 2026-05-27T08:01:50Z is unaffected; this memo is documentation only.
- **No new findings or hypotheses.** Everything in this memo is synthesized from Phases 1-5. If something here reads as "new," it is a re-framing of an existing finding, not a discovery.
- **Live-flip remains operator-only.** Per the autonomy contract, no autonomous session may flip C3 (or anything else) from paper to live based on this memo. The recommendation is for operator review only.

---

## Cross-references

### B.1.5 harness materials
- **Harness spec (full methodology):** [docs/specs/b15_backtest_harness.md](../specs/b15_backtest_harness.md) — Phases 3, 3.5, 4, 5 all documented with per-strategy tables, regime feature tables, and gating re-test tables.
- **Data inventory:** [docs/specs/b15_data_inventory.md](../specs/b15_data_inventory.md)
- **Original session-9 spec:** [docs/decisions/2026-05-22_b15_backtest_harness.md](2026-05-22_b15_backtest_harness.md)
- **Raw outputs (all in `data/backtest_results/`):**
  - `slippage_sweep_2026_05_27.json` (Phase 3.5 — C1/C3/C6 break-evens)
  - `slippage_sweep_c1_2026_05_27.json`, `slippage_sweep_c3_2026_05_27.json`, `slippage_sweep_c6_2026_05_27.json`
  - `c3_walkforward_6mo_2026_05_27.json` (Phase 4 — 5×60d windows)
  - `c3_regime_gate_2026_05_27.json` (Phase 5 — features + gate + re-test)
  - `c3_60d_summary.json` (Phase 3 original orchestrator)

### Phase memory anchors (read for history + design rationale)
- `[[aaats-2026-05-27-b15-gap-analysis]]` — overall B.1.5 anchor, Phase 1-2 context
- `[[aaats-c3-slippage-fragility]]` — live C3 path applies zero slippage; soak PnL biased optimistic
- `[[aaats-2026-05-27-b15-phase4-c3-walkforward]]` — WINDOW-DEPENDENT verdict, 5×60d windows
- `[[aaats-2026-05-27-b15-phase5-regime-gate]]` — GATE-INEFFECTIVE verdict, fingerprint + gate spec
- `[[feedback-regime-filtering-at-allocator]]` — durable rule from Phase 5: regime-awareness belongs at allocator, not inside single-strategy code

### Locked doctrine + amendments
- **Locked doctrine:** [docs/operator/aaats_locked_doctrine_2026_05_14.md](../operator/aaats_locked_doctrine_2026_05_14.md)
- **Doctrine amendment (paper floor $100→$200):** [docs/decisions/2026-05-23_doctrine_amendment_200_floor.md](2026-05-23_doctrine_amendment_200_floor.md) — relevant because all per-strategy PnL in B.1.5 was computed against a $100 starting capital harness replay; live equity-fractional sizing is $200 baseline. Doctrine elements (G1–G5 tranches, kill thresholds, $50/mo split) all unchanged by this proposal.
- **Autonomy contract:** [docs/decisions/2026-05-21_autonomy_contract.md](2026-05-21_autonomy_contract.md) — live-flip remains operator-only.

### Operational
- **D.5 soak runbook:** anomaly-window counter, day-30 ETA 2026-06-22.
- **Operator-return procedure:** [docs/runbooks/operator_return_resume_procedure.md](../runbooks/operator_return_resume_procedure.md) — read this *before* acting on any recommendation in this memo.
