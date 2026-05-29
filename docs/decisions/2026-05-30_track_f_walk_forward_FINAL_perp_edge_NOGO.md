# Track F walk-forward — FINAL ARBITER of the perp-edge program: NO-GO

**Status:** TERMINAL DECISION — verdict stands, not re-litigated. Offline backtest on cached contiguous data; D.5 soak untouched, no deploy, no infra.
**Authored:** 2026-05-30 (machine clock 2026-05-29 → artifact filenames carry the 2026-05-29 stamp).
**Reads with:** [static ensemble + economics](2026-05-30_track_f_static_ensemble_and_economics.md), [Track F F.1](2026-05-30_track_f_f1_perp_tsmom_and_c7_close.md), [Track 11](2026-05-29_b17_track11_drift_gate_and_track_e_entry.md).

---

## TL;DR

The operator-approved walk-forward — the pre-committed FINAL arbiter — returns **NO-GO**. The static equal-weight C3+TSMOM ensemble, tested out-of-sample across **15 non-overlapping 2-month folds over 36 months** of contiguous perp history, misses **4 of the 5 frozen criteria**. The decisive failure is the **null control**: the ensemble's pooled-OOS Sharpe (+0.818) is *below* the 95th percentile of a random sign-shuffle (+1.097) — its 36-month out-of-sample performance is **statistically indistinguishable from randomly-signed trades**. No threshold was tuned to results; the verdict is terminal.

**Per the frozen terminal semantics: STOP the strategy hunt. No iteration, no re-spec, no 6th strategy. The doctrine fork (§4) is now the operator's.** This closes the perp-edge program (C3 reversion → C7 carry → TSMOM momentum → static ensemble → walk-forward).

---

## 1. Data + design (as frozen)

- **Contiguous data:** fetched 36mo (2023-05-28 → 2026-05-27) of USDT-M perp 1h klines + funding for all 6 symbols (BTC/ETH/SOL/LINK/AVAX/DOT), 26,295 bars each. Every symbol covers the full span — **no listing/survivorship truncation** (all 6 perps listed well before 2023; the 24mo floor is cleared with margin). Fetcher: `tools/backtest/fetch_perp_data.py` `--window contig`.
- **Walk-forward:** rolling-origin 4mo-train / 2mo-OOS, step 2mo, non-overlapping OOS → **15 folds** (≥10 required). Strategies are not fitted (frozen C3 gate_version=1; TSMOM L=336h/REBAL=24h), so each is run once continuously over the full history on a $100 book and trades are bucketed into OOS folds by close timestamp. Equal-weight (50/50 sleeve) ensemble is the gated unit. Harness: `tools/nautilus/run_walk_forward.py`. Raw output: `data/graduation/walk_forward_result_2026-05-29.txt`.

## 2. Result — the frozen 5-part criterion

| # | Criterion (frozen threshold) | Observed | Verdict |
|---|---|---|---|
| 1 | OOS net > 0 in ≥ 60% of folds | **53.3%** (8/15) | **FAIL** |
| 2 | median per-fold OOS Sharpe ≥ 0.50 (per-trade sqrt60) | **+0.304** | **FAIL** |
| 3 | pooled-OOS daily Sharpe ≥ 1.0 (sqrt365; daily mean +0.00052, std 0.01211) | **+0.818** | **FAIL** |
| 4 | worst single-fold maxDD ≤ 20% | 13.8% | PASS |
| 5 | pooled-OOS Sharpe > 95th pct of sign-shuffle null | real **+0.818** vs p95 **+1.097** | **FAIL** |

**4 of 5 missed → NO-GO.**

**Per-fold (regime alternation is visible):** positive in trending/up regimes (fold 7 +$26.94 at BTC-60d +46%; fold 8 +$14.02; folds 0–3 modestly positive) and sharply negative in choppy/down regimes (fold 6 −$13.80; fold 12 −$11.45; fold 9 −$5.18). The ensemble alternates sign with regime — the same fragility every single-factor class showed, now confirmed across 15 folds rather than 2 windows.

**On criterion 3's annualization (documented for transparency):** "annualized identically to G2" is not literally portable — G2 is a per-trade sqrt(60) proxy, and criterion 3 explicitly specifies *daily* returns ("not a per-trade sqrt scaling"). The standard 24/7-crypto daily annualization sqrt(365) was used at the frozen ≥1.0 bar. The raw daily mean (+0.00052) is barely positive and the std (0.01211) large, so the verdict is robust to the annualization choice — under sqrt(252) the pooled Sharpe is ~+0.68, still well below 1.0. Criterion 3 fails under any reasonable convention.

**The null control is the load-bearing result.** Even taking the ensemble's full-period numbers at face value (+$47.29 pooled-OOS net over 1,398 trades, pooled daily Sharpe +0.818 — *positive*), the sign-shuffle permutation test shows that a strategy of the **same trades with random long/short signs** achieves a higher Sharpe 5%+ of the time (p95 = +1.097 > +0.818). The observed directional edge is therefore **not statistically distinguishable from luck**. A positive backtest PnL that cannot beat its own randomized-sign null is not an edge.

## 3. Diagnostics (reported, NOT gated)

- **C3-only** pooled-OOS daily Sharpe **−1.279** over 36mo: the C3 alt/BTC mean-reversion edge that PASSED the single current 6mo window is **net-negative across the full contiguous history**. Its earlier success was regime-specific, exactly as Tracks 8–11 suspected.
- **TSMOM-only** pooled-OOS daily Sharpe **+1.003**: momentum is the stronger leg over 36mo (≈ the 1.0 bar on its own) — but it still failed its own 2-window gate (Track F F.1) and does not carry the gated ensemble past the criteria, and a single-leg result is not what was gated.
- **Inverse-vol** weighting (0.82 C3 / 0.18 TSMOM) pooled-OOS net +$4.37 — worse than equal-weight, because it over-weights the negative-Sharpe C3 leg. No weighting rescues it.

## 4. Decision

| Item | Result |
|---|---|
| Walk-forward (15 folds, 36mo, OOS, null-controlled) | **NO-GO** — 4/5 criteria missed |
| Decisive failure | null control: edge indistinguishable from random signs |
| C3 reversion over 36mo | net-negative (Sharpe −1.28) — regime-specific, not robust |
| Perp-edge program (C3 / C7 / TSMOM / ensemble) | **CLOSED — no robust edge found** |
| Next | **Operator doctrine fork (below). No 6th strategy, no re-spec.** |

No infra built. No deploy. The graduation gate, the harness family, and the walk-forward apparatus remain reusable for any *future* thesis the operator chooses — but the directional/reversion crypto-perp thesis at this universe and scale is exhausted by evidence.

## 5. Doctrine fork — operator decision (the walk-forward verdict stands either way)

The pre-registered terminal semantics forbid iterating on another strategy. The remaining question is doctrine-level, and it is the operator's:

- **A — Pause/abandon the directional-crypto live-flip.** No demonstrable edge survives an honest OOS multi-regime null-controlled test; deploying $25 of real capital into it is unjustified. Keep the D.5 paper soak running as a monitored research bed (the L1–L10 operational stack is the part that *works*), but do not flip to live on this thesis. Lowest-risk, evidence-aligned.
- **B — Pivot the thesis/asset class.** Non-directional or microstructure edges (majors market-making, cross-venue basis, liquidity provision) are less regime-fragile but need data AAATS lacks (order book) and new infra — a major, multi-session commitment that should start with a data-feasibility check, not a strategy.
- **C — Re-examine the premise.** Across every class, the edge is regime-conditional and, at the directional level, not better than chance. The honest read is that small-notional directional crypto on a 6-symbol majors+alts universe may simply not contain a deployable edge for this operator's constraints. Redirecting effort to where AAATS demonstrably excels (operational reliability, monitoring, the soak infrastructure) may dominate continuing the edge hunt.

**Recommendation (operator decides):** A — pause the live-flip, keep the soak as a research bed, and treat any future edge work as a fresh thesis with its own pre-registered gate, not a continuation of this program. The evidence does not support spending more cycles or any real capital on the current directional-perp thesis.

## 6. Reproduce

```
python tools/backtest/fetch_perp_data.py --window contig         # idempotent contiguous fetch
.venv-nt/Scripts/python tools/nautilus/run_walk_forward.py       # 15-fold walk-forward + 5-part criterion
```
Raw verdict: `data/graduation/walk_forward_result_2026-05-29.txt`.
