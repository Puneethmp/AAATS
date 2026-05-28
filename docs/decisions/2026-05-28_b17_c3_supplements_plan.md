# Phase B.1.7 — C3-class supplements + held-out C3 retune (ensemble live-flip)

**Status:** PROPOSED — planning, no runtime impact. Workstation-only research track; the box keeps running AAATS untouched.
**Authored:** 2026-05-28 (Cowork session, post-B.1.6 verdict).
**Premise:** B.1.6 produced C3's first honest verdict on a realistic cost model: **FAIL by 0.03 on G5** (PF 1.27 vs 1.30), all six other criteria PASS, +6.3% net of Binance VIP-0 fees over 6mo OOS. The cheap response — "tune until PF crosses 1.30" — is the overfitting trap the gate exists to prevent. The right response, already pointed at by the B.1.5 Phase 3.5 memo, is **build C3-class supplements** and graduate an ensemble.
**Supersedes:** the "tune C3 vs accept lower threshold vs build supplements" decision recorded in [`2026-05-27_c3_nautilus_port_and_graduation_gate.md`](2026-05-27_c3_nautilus_port_and_graduation_gate.md). This doc records the answer.

---

## Why we are NOT taking the easy path

### Why not (a) — naive C3 retune on the same window

C3 has already been tuned twice (2026-05-12 Phase 1 + 2026-05-13 v2 vol-adjusted sizing/trailing exit/cooldown). A third sweep on the *same 6mo window that produced PF 1.27* and stopping when PF crosses 1.30 contaminates the only honest OOS evidence we have. The "OOS" stops being out-of-sample the moment we tune against it. The disciplined variant of (a) — tune on an earlier window, validate unchanged on the current one — is fine and is included below as the C3* track.

### Why not (b) — lower the G5 threshold

Lowering 1.30 → 1.25 *after* seeing 1.27 is the rationalization the gate was built to prevent. The gate's "Tuning" section says thresholds may be tuned "once real graduations accumulate" — i.e., after multiple strategies have passed cleanly and live outcomes have calibrated the bar — not after the first one fails. Move the bar now and every future near-miss strategy gets the same favour. The gate becomes negotiable, which is the same as having no gate.

### Why (c) is right

Three converging reasons:

1. **The B.1.5 Phase 3.5 memo already pointed here** — "Option C direction: C3-class — mean-reversion on alt-vs-BTC pairs. Don't build more stat_arb or bollinger-range variants." This isn't a new direction; it's the action the memo deferred to operator decision.
2. **Single-strategy edge is fragile for unattended live trading.** Even if C3 graduated at PF 1.31 tomorrow, deploying it alone gives the bot one edge source. Any regime where alt/BTC mean reversion breaks down (sustained trending, BTC-dominance spike) takes the whole book offline. L9 protects capital; nothing protects the edge.
3. **It validates the gate itself.** C3 was the pilot. If the gate only ever runs on one strategy, you don't know whether it's a real promotion bar or a C3-specific filter. Putting 2 more strategies through it proves the pipeline is general — which is the actual long-term asset of the combine-both architecture.

---

## The plan — three parallel tracks, one ensemble decision

### Track 1 — C3c (ETH-anchored mean reversion) — FIRST

**Hypothesis:** Many alt/BTC mean-reversions are confounded by ETH/BTC drift (BTC.D rises, alts dump together against BTC regardless of their own value). Anchoring against ETH instead may produce cleaner signals for DeFi-aligned alts.

**Spec — minimal diff from C3:**

| Field | C3 | C3c |
|---|---|---|
| Reference asset | `BTC/USDT` | **`ETH/USDT`** |
| Signal | z-score of `log(ALT/BTC)` | z-score of `log(ALT/ETH)` |
| Universe | SOL/LINK/AVAX/DOT | SOL/LINK/AVAX/DOT (same — they're ETH-correlated enough) |
| Macro gate (RSI) | BTC RSI > 35 | **BTC RSI > 35 (KEEP)** — BTC freefall still nukes everything |
| Macro gate (dominance) | BTC.D fast-rise filter | **KEEP** — alt-season filter applies regardless of reference |
| Lookback | 60 bars | 60 bars (identical) |
| Z thresholds | -1.6 / -2.6 / 0.5 / -0.3 / 0.4 | identical |
| Sizing | $10 vol-adjusted | identical |
| Cooldown / denylist | 24h / OP+ARB+PUMP+FET+LUNC | identical |
| STRATEGY_ID | `C3_altcoin_reversion` | `C3c_alt_eth_reversion` |
| STATE_FILE | `data/altcoin_reversion_state.json` | `data/c3c_eth_anchored_state.json` |

**Implementation approach:** clone `tools/nautilus/run_c3_oos.py` → `tools/nautilus/run_c3c_oos.py`, change two constants (`BTCSYM` → `ETHSYM`, swap data load), update strategy id, run the same gate. ~30 LOC diff. No changes to `trading/altcoin_reversion.py` (the box runs that, leave it alone). C3c stays paper-only inside NT until graduation.

**Estimate:** 1 session.

**Expected outcome:** unknown — that's the point. If C3c PASSES at PF ≥ 1.30, you have two graduation candidates and the ensemble thesis is validated. If C3c FAILS at similar metrics, you've learned that the edge isn't reference-asset-specific (it's an alt-vs-major-crypto phenomenon, not specifically alt/BTC) — useful information. If C3c FAILS hard, ETH-anchored isn't the right diversifier and C3b becomes the candidate.

### Track 2 — C3b (longer-lookback variant) — SECOND

**Hypothesis:** C3's 60-bar (2.5d) lookback captures short-cycle reversions. A 120-bar (5d) lookback exposes slower divergences, providing time-scale diversification within the same architecture.

**Spec:**

| Field | C3 | C3b |
|---|---|---|
| Reference | BTC/USDT | BTC/USDT (same) |
| Universe | SOL/LINK/AVAX/DOT | SOL/LINK/AVAX/DOT (same) |
| **Lookback** | **60 bars** | **120 bars (2x)** |
| **Z_ENTRY** | **-1.6** | **-1.8** (slightly tighter to compensate for longer-tail noise) |
| **TIME_STOP_HOURS** | **24** | **72** (longer reversion = longer hold) |
| All other params | (as C3) | identical |
| STRATEGY_ID | `C3_altcoin_reversion` | `C3b_long_lookback` |

**Implementation:** clone harness same as Track 1, override 3 constants. ~20 LOC diff.

**Estimate:** 0.5 session (cloned from C3c work).

### Track 3 — C3* (held-out C3 retune) — THIRD, disciplined

**Premise:** A param sweep on C3 is *only* honest if winning params are validated on data the sweep never saw. Binance has 1h history well before 2025-11; the existing fetch in `data/historical/` covers 2025-11 → 2026-05 (the current 6mo). Extend the cache backward.

**Spec:**

1. Extend `tools/backtest/historical_data.py` (or write `historical_data_v2.py` if the existing API doesn't take date ranges) to fetch 1h bars for 2024-11-28 → 2025-05-27 for BTC + SOL/LINK/AVAX/DOT/ETH.
2. Run a param sweep on the EARLIER window, varying:
   - `Z_ENTRY ∈ {-1.4, -1.6, -1.8, -2.0}`
   - `Z_TRAILING_DROP ∈ {0.3, 0.4, 0.5}`
   - 12 combinations total.
3. Pick the combination with highest PF on the earlier window. Call it C3*.
4. Run C3* **unchanged** through `run_c3_oos.py` on the current 2025-11 → 2026-05 window — which is now genuinely held out.
5. If C3* produces PF ≥ 1.30 on the current window, it graduates. If not, C3* is rejected; the C3 architecture is honestly maxed.

**Estimate:** 1.5 sessions (fetch + sweep + held-out validation).

**Critical discipline:** if step 3's winning PF on the earlier window is dramatically higher than C3's current PF (e.g. PF 1.8 in-sample), and step 4's held-out PF collapses (e.g. PF 1.05), that's exactly the overfitting signature and C3* must be rejected — even if you could find a different sweep with better held-out PF, that would just be re-tuning against the held-out window.

---

## Live-flip decision rule (locked)

The first live $25 tranche fires when **≥ 2 of {C3, C3*, C3b, C3c}** hold PASS graduation reports in `data/graduation/`. C3 itself is excluded from the count *unless* it eventually PASSES via the C3* honest retune — C3 at PF 1.27 does not graduate by relaxed threshold.

Capital splits proportionally to OOS Sharpe across graduated strategies. The $200 paper floor / $25 first tranche / 5-gate live promotion ladder from the locked doctrine are unchanged.

If only one of the three supplements PASSES, the live-flip waits. Single-strategy live deployment is rejected by the same diversification reasoning that drives this whole phase.

---

## Risks

1. **All three supplements fail.** Possible. Means alt-vs-major mean reversion as an architecture is at PF ~1.25-1.30 ceiling for this period and we need a fundamentally different strategy class (e.g., funding-rate arb, momentum breakout on a different time scale, market-making on majors). Track E (futures/perps) opens up. The harness still ran 3 strategies through the gate — the pipeline is proven and reusable for any next-class candidate.
2. **All three PASS.** Best case. Deploy ensemble per the rule.
3. **C3c PASSES, C3b FAILS, C3* FAILS.** Likely middle case. Deploy a 2-strategy ensemble (original C3 paper + C3c live), with C3 staying paper-only as a sanity reference. Actually — if C3c is the only PASS, single-strategy concern returns; recommend running Track 3 a second time with different sweep params before live-flip.
4. **NT API churn.** Pinned `nautilus_trader==1.202.0` in requirements-dev.txt. Don't bump mid-phase.
5. **C3c overfits to the same period as C3.** Both run on the same 2025-11 → 2026-05 window. If both PASS, they could share regime exposure (both benefit from the same alt-season dynamic). Mitigation: add a correlation check on per-trade PnL between C3 and C3c in the ensemble step; if correlation > 0.7, treat them as one strategy for sizing.

---

## Timeline + the one move that matters

| Step | Sessions | Produces |
|---|---|---|
| Track 1 — C3c implementation + gate run | 1 | C3c graduation report |
| Track 2 — C3b implementation + gate run | 0.5 | C3b graduation report |
| Track 3 — earlier data + sweep + held-out validation | 1.5 | C3* graduation report |
| Decision — ≥2 PASS → live-flip Track C kicks off | 0.5 | live-flip GO/NO-GO |

**~3.5 Sonnet sessions to a defensible live-flip decision.** The single highest-leverage first move is **C3c** because (a) it's the smallest code change (~30 LOC), (b) it tests the most independent hypothesis (different reference asset = different beta structure), and (c) a clean PASS would immediately give the ensemble two candidates without touching C3. The paste-ready prompt below dispatches that session.

---

## Open questions for operator

1. **Approve the live-flip rule "≥ 2 of {C3, C3*, C3b, C3c} PASS"?** Recommended: yes. Tightens to ≥3 if you want even more cushion at the cost of more sessions before live.
2. **Acceptable to fetch ~6 months of Binance public klines on workstation?** Free, no auth, used by existing harness. Recommended: yes.
3. **C3c session first, or all three in parallel?** Recommended: C3c first, in serial. Parallel sessions can race and the C3* track depends on Track 1's harness refactor being settled.

---

## Paste-ready Claude Code prompt — Track 1 (C3c) implementation

Paste this into a Claude Code session on the workstation. It's self-contained, decisions baked in, no clarifying round-trips needed.

```
You are executing AAATS Phase B.1.7 Track 1 — C3c (ETH-anchored alt mean
reversion) implementation + graduation gate run. Full plan:
docs/decisions/2026-05-28_b17_c3_supplements_plan.md.

CONTEXT (read this first):
- B.1.6 just shipped: NT-native graduation harness lives at
  tools/nautilus/run_c3_oos.py, gate at tools/graduation/gate.py, spec at
  docs/specs/graduation_gate.md. C3's verdict was FAIL by 0.03 on G5
  (PF 1.27 vs 1.30), all other criteria PASS.
- Decision (this phase): do NOT re-tune C3 on the same window. Build
  C3-class supplements. C3c is the first.
- requirements-dev.txt pins nautilus_trader==1.202.0. NT requires
  Python 3.10-3.12; if the workstation venv is 3.14, create a 3.11 venv:
       py -3.11 -m venv .venv-nt
       .venv-nt\Scripts\activate
       pip install -r requirements-dev.txt
- C3c does NOT touch trading/altcoin_reversion.py or anything the box runs.
  This is workstation-only research code.

DO THIS:

1. Verify the existing harness reproduces. From the repo root in the NT venv:
       python tools\nautilus\run_c3_oos.py
   Expect VERDICT: FAIL, G5 the only failure, PF 1.27, n_trades 242.
   If anything else, STOP and investigate before adding C3c.

2. Confirm the 6mo ETH parquet exists (it should — ingested as part of B.1.5):
       Test-Path data\historical\ETH_USDT_1h.parquet
   If False, fetch it via the existing tools/backtest/historical_data.py
   for the 2025-11-28 to 2026-05-27 window.

3. Create tools/nautilus/run_c3c_oos.py by cloning run_c3_oos.py with
   these MINIMAL changes (everything else identical, including the gate
   call and report emission):

   - Module docstring: change "C3 altcoin-reversion" -> "C3c ETH-anchored
     altcoin-reversion (B.1.7 Track 1)" and reference this decision doc.
   - Replace BTCSYM = "BTC" with ETHSYM = "ETH" everywhere it's used as
     the REFERENCE asset. KEEP a BTC bar subscription — the BTC RSI macro
     gate stays in place (BTC freefall still nukes everything regardless
     of reference asset). Strategy needs TWO reference buffers:
     self.closes["ETH"] used for z-score, self.closes["BTC"] used for RSI.
   - UNIVERSE stays ["SOL", "LINK", "AVAX", "DOT"].
   - On_bar clock: trigger the C3 cycle on the ETH bar (not BTC), since
     ETH is now the z-score reference. Apply ts_init_delta=1 to ETH bars
     so they process AFTER all alt bars at each timestamp. Keep BTC bars
     with ts_init_delta=0.
   - In the entry/exit phase, build TWO DataFrames: eth_df for the z-score
     (passed to c3._compute_z_score) and btc_df for the RSI gate
     (c3._rsi(btc_df["close"])).
   - Engine trader_id: "C3c-NT-001".
   - Report strategy name: "C3c_alt_eth_reversion" passed to emit_report.

4. Run the harness:
       python tools\nautilus\run_c3c_oos.py
   This writes data/graduation/C3c_alt_eth_reversion_<today>.json. Capture
   the full output.

5. Compare C3c metrics against C3 (B.1.6 baseline):
   - C3: PF 1.27, Sharpe 1.24 OOS, +$6.32, 242 trades, 48.8% WR
   - C3c: <whatever it produces>
   Print a side-by-side table.

6. Commit atomically:
       git add tools\nautilus\run_c3c_oos.py
       git add -f data\graduation\C3c_alt_eth_reversion_<today>.json
       git add docs\decisions\2026-05-28_b17_c3_supplements_plan.md
       git commit -m "B.1.7 Track 1: C3c ETH-anchored alt mean-reversion harness
       + first NT graduation run (VERDICT: <PASS|FAIL>)

       Net <pnl_usd> on 100 over 6mo OOS, Sharpe <oos_sharpe>, PF <pf>,
       <n_trades> trades. <PASS|FAIL> with <failures> as blockers.
       Reuses C3 pure functions verbatim; box untouched."
       git push origin main

7. WRITE the verdict back to me in this format (3-5 sentences max):
   - VERDICT: PASS | FAIL
   - Which criteria PASS/FAIL with actuals
   - Comparison to C3 (PF, Sharpe, trade count delta)
   - Recommendation: proceed to C3b? rerun with different param? abort?

DO NOT:
- Modify trading/altcoin_reversion.py (the box runs that, leave it alone).
- Lower any G1-G7 threshold to make C3c PASS. The gate is non-negotiable.
- Tune C3c constants iteratively against the same data. If C3c FAILS,
  report the failure honestly and move on to Track 2 (C3b).
- Wire C3c into live_paper_runner.py. C3c is paper-only inside NT until
  it earns a graduation report.

GUARDRAILS (don't skip):
- Pre-commit ruff may auto-format; run `pre-commit run --files tools\nautilus\run_c3c_oos.py`
  BEFORE git add to avoid the documented race (deploy_lib.py rule #5).
- The box keeps running AAATS. Do not touch deployment/, scripts/box/, or
  anything in execution/, risk/, foundation/. This is workstation-only.
```

---

## References

- B.1.6 verdict: `data/graduation/C3_altcoin_reversion_2026-05-28.json`
- Final NT extraction: [2026-05-27_nt_final_extraction_for_success.md](2026-05-27_nt_final_extraction_for_success.md)
- C3 source: [trading/altcoin_reversion.py](../../trading/altcoin_reversion.py)
- NT harness: [tools/nautilus/run_c3_oos.py](../../tools/nautilus/run_c3_oos.py)
- Gate: [tools/graduation/gate.py](../../tools/graduation/gate.py), spec: [docs/specs/graduation_gate.md](../specs/graduation_gate.md)
- B.1.5 Phase 3.5 doctrine that pointed at this direction: memory `aaats-2026-05-27-b15-phase35-breakeven`
