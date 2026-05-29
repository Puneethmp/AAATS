# Track F — static ensemble rejected + fee economics → Branch 2 (gate construction is the suspect)

**Status:** DECISION — verdict locked. Offline backtest analysis on data already on disk (no new fetch, no infra, no deploy). D.5 soak untouched.
**Authored:** 2026-05-30 (machine clock 2026-05-29 → artifact filenames carry the 2026-05-29 stamp).
**Reads with:** [Track F F.1](2026-05-30_track_f_f1_perp_tsmom_and_c7_close.md), [Track 11](2026-05-29_b17_track11_drift_gate_and_track_e_entry.md). Memories `aaats-2026-05-30-track-f-f1-perp-edge-trials`, `aaats-2026-05-29-track11-drift-gate`.

---

## TL;DR

The operator rejected building a regime-conditional ensemble (Option A) on a math argument, asked to confirm it cheaply and then test whether fee economics moot the strategy hunt. Both done from cached data:

1. **Static C3+TSMOM ensemble FAILS both windows** (G2/G5/G6), equal-weight AND inverse-vol. It nets positive full-period (G1 passes) but the **OOS mean return is negative in both windows**, so OOS Sharpe is negative — exactly the linear-mean prediction, and it holds regardless of weights or correlation. Option A is correctly rejected: it can only "pass" by overfitting a timing overlay.
2. **NOT fee-dominated.** The edge clears the ~10bps taker floor in both windows (break-even 18–70bps round-trip; net positive). Fees are 14% of the gross edge where it's strong, 55% where it's weak. Contrast C7 (funding was 1/22 of fees). Net sign is tranche-invariant — raising the tranche cannot rescue it; only a lower fee tier moves the needle, and there's already headroom.
3. **→ Branch 2.** Since the ensemble fails but the edge clears fees, the binding constraint is NOT capital/fees — it is regime-robustness, and the gate's **2-month OOS over 2 hand-picked windows is small-sample**. The honest next test is a walk-forward across many regime-tagged sub-periods with a **pre-registered** robustness criterion. **Scoped below; NOT run this session.**

No strategy was swept, the G1–G7 gate is unchanged, no 3rd single-strategy trial, no infra.

---

## 1. Task 1 — static ensemble confirmation

Re-ran the C3-perp-gated (gate_version=1, the divergence gate — v2 inert, v3 harmful) and Perp-TSMOM per-trade ledgers for both windows from cached parquet data, blended them, and scored the UNCHANGED G1–G7 gate. Equal-weight = 50% capital sleeve to each on a $100 book; the per-trade return is sleeve-invariant, so the pooled per-trade sqrt(60) Sharpe matches the harness family's convention exactly. Script: [run_ensemble_and_economics.py](../../tools/nautilus/run_ensemble_and_economics.py).

```
window  | C3 net | TSM net| EW net | oosShrp | isShrp |  PF  | maxDD | verdict
current | +8.29  | -5.16  | +1.57  |  -1.65  |  0.55  | 1.05 | 0.147 | FAIL
earlier | -4.86  | +20.30 | +7.72  |  -0.91  |  0.93  | 1.24 | 0.081 | FAIL
```

Per-criterion (equal-weight): **G1 ok, G3 ok, G4 ok, G7 ok; G2 FAIL, G5 FAIL, G6 FAIL — both windows.**

**Linear-mean evidence (the load-bearing result):** the blended OOS mean per-trade return is negative in *both* windows, so OOS Sharpe is negative, so G2 (≥1.0) and G6 (OOS ≥ 0.5·IS) both fail:

```
current: C3 OOS mean ret +0.01123 (pnl +5.43) | TSMOM OOS mean ret -0.02264 (pnl -14.94) -> blend OOS mean -0.00764
earlier: C3 OOS mean ret -0.00578 (pnl -2.64) | TSMOM OOS mean ret -0.01389 (pnl  -7.71) -> blend OOS mean -0.00901
```

In the *earlier* window both legs lose OOS (the operator's case). In the *current* window C3's positive OOS (+5.43) is swamped by TSMOM's catastrophic OOS (−14.94), so the blend OOS is negative there too. A portfolio mean is linear in its components, so any positive-weighted blend of two negative-OOS-mean legs has a negative OOS mean — **independent of correlation** (correlation only changes the OOS *std*, never the sign of the mean). Confirmed by the inverse-vol blend, which fails identically:

```
current: w(C3,TSMOM)=(0.74,0.26)  net +4.85  oosShrp -1.65  -> FAIL
earlier: w(C3,TSMOM)=(0.77,0.23)  net +1.01  oosShrp -0.91  -> FAIL
```

**Verdict: the static ensemble does not graduate, under either weighting.** Option A (regime-conditional ensemble) is rejected: the only way to make it pass would be a regime/timing overlay fitted to which 2-month slice is good — i.e., overfitting the timing to these two windows. Reports: `data/graduation/Ensemble_EW_{current,earlier}_2026-05-29.json`.

## 2. Task 2 — economics floor

Equal-weight blend on a $100 book, taker fees (C3 round-trip = 2×5bps on position notional; TSMOM round-trip = 2×5bps on traded notional):

```
window  | EW net | EW fees | pre-fee net | fee % of gross | break-even RT | $25-tranche net
current | +1.57  |  1.91   |    +3.47    |     54.9%       |    18.2 bps    |   +$0.39
earlier | +7.72  |  1.29   |    +9.00    |     14.3%       |    70.0 bps    |   +$1.93
```

- **The edge clears the fee floor in both windows** — net is positive after fees, and the break-even round-trip fee (18.2 / 70.0 bps) sits above the ~10bps taker actually charged. This is **not** the C7 situation (there, funding income was ~1/22 of fees and net was negative regardless).
- Fees are a **secondary** constraint that bites hardest where the edge is weakest: 14% of gross in the earlier window (strong edge), but 54.9% in the current window (weak gross edge because TSMOM has no current-regime edge). So where the signal works, fees are a modest tax; where it doesn't, the problem is the signal, not the fee.
- **Tranche size is irrelevant to the sign.** Percentage-based fees scale gross and fees together, so the net *sign* and the fee *fraction* are invariant to tranche size — raising the $25 tranche cannot turn a losing strategy positive (it only scales the dollars). At $25, the (positive but tiny) full-period nets are +$0.39 / +$1.93 over 6 months. The only economic lever is the fee TIER (maker ~4bps, or VIP), and there is already break-even headroom at taker.

**Conclusion: the binding constraint is NOT capital/fees.** It is regime-robustness — the OOS edge sign.

## 3. Decision

| Item | Result |
|---|---|
| Static ensemble (equal-weight) graduates both windows? | NO — FAIL G2/G5/G6 both |
| Static ensemble (inverse-vol)? | NO — fails identically (sign is weight-invariant) |
| Option A (regime-conditional ensemble) | REJECTED (can only pass by overfitting timing) |
| Edge clears the ~10bps taker fee floor? | YES (net +ve both windows; break-even 18–70bps) |
| Fee/capital the binding constraint? | NO (contrast C7) |
| **Branch fired** | **Branch 2 — gate construction is the suspect** |
| Next | Scope Option B walk-forward (below); operator approves the pre-registered criterion before any run |

No infra built. No 3rd single-strategy trial. No deploy.

## 4. SCOPED — Option B walk-forward (NOT run this session; for operator approval)

The 2-month OOS over 2 hand-picked windows is small-sample; it cannot distinguish "no robust edge" from "two unlucky OOS slices." A walk-forward across many regime-tagged sub-periods can — **but only if the robustness criterion is committed before the results are seen**, or it degenerates into curve-fitting (the failure mode that killed the C3 entry-gate program). The honest prior is skeptical: the OOS edge is negative in both current windows, which is also consistent with genuine overfitting. The walk-forward is the disambiguator, not a presumed rescue.

**Prerequisite (data):** the two cached windows are disjoint (earlier Nov24→May25, current Nov25→May26, with a ~6mo gap and nothing before Nov24). A walk-forward needs *contiguous* history. Step 0 is therefore a fetch of contiguous 6-symbol perp klines+funding over ≥18–24 months (extend `fetch_perp_data.py` with a contiguous window) — a soak-safe data fetch, not infra.

**Design:**
- Folds: 4-month train / 2-month test, rolled forward by 2 months across the contiguous history → ≥7 non-overlapping OOS folds. (Matches the current gate's IS/OOS shape so per-fold numbers are comparable.)
- Subject: the static equal-weight C3+TSMOM ensemble (and each leg, for attribution). No regime detector, no timing overlay — same static blend rejected above, now tested for robustness across many regimes instead of two.
- Tag each fold by regime (BTC 60d return sign; realized-vol quartile) for diagnosis only — NOT used to select folds.

**PRE-REGISTERED robustness criterion (committed here, before running — operator to approve or amend BEFORE any run):** the ensemble is declared robust iff ALL of:
1. ensemble OOS net PnL > 0 in **≥ 60%** of folds;
2. **median** per-fold OOS Sharpe ≥ **0.5**;
3. the **pooled** all-OOS-folds per-trade Sharpe (sqrt(60), the G2 bar applied to the union of every OOS fold — a far larger sample than 2 months) ≥ **1.0**;
4. worst single-fold drawdown ≤ **20%** (the G3 bar).

If met → a genuine regime-robust edge exists → proceed to Track F infra sequencing (B1 doctrine → B4 schema → B2 margin/liq → B3 adapter → F.5 paper-futures soak). If not met → the edge is genuinely regime-specific/absent; STOP the strategy hunt and escalate the doctrine fork (the binding constraint is then the strategy universe, not the gate). **These four thresholds are frozen; do not tune them to the walk-forward output.**

## 5. Reproduce

```
.venv-nt/Scripts/python tools/nautilus/run_ensemble_and_economics.py
```
Reports: `data/graduation/Ensemble_EW_{current,earlier}_2026-05-29.json`.
