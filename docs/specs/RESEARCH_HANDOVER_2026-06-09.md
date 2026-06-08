# AAATS Research Handover — 2026-06-09

State snapshot for a fresh agent with no prior context. Factual; describes
current state, not plans. Where something is planned-but-not-done, it says so.

> **Session scope disclaimer.** The 2026-06-08/09 session reached **Phase 1
> audit (approved) and Phase 2 design (approved)** only. NOTHING was deleted,
> moved, or implemented. No new thesis was run. The fill model does NOT exist
> yet. Sections below distinguish DONE from PENDING explicitly.

---

## 1. What was verified

| Item | Status | Detail |
|---|---|---|
| 2026-05-30 NO-GO replication | **NOT RE-RUN THIS SESSION** | The Track F arbiter ([tools/nautilus/run_walk_forward.py](../../tools/nautilus/run_walk_forward.py)) was **read and confirmed intact and internally coherent** (frozen 5-part criterion, sign-shuffle null seed=7, 1000 draws). It was **not yet independently executed** — independent re-derivation is a PENDING P0 task. The documented verdict (NO-GO, 4/5 criteria missed) at [docs/decisions/2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md](../decisions/2026-05-30_track_f_walk_forward_FINAL_perp_edge_NOGO.md) is **accepted on documentation, not yet on a re-run**. |
| Falsification harness present | **VERIFIED** | `tools/nautilus/` holds 25 files incl. `run_walk_forward.py`, `null_engines.py`, `xsect_walkforward.py` (the `evaluate()` 5-part gate), `basket_ledger.py`, `u30_data.py`, `xsect_signals.py`. Crown-jewel methodology intact. |
| Discrepancy found | **ONE, benign** | An initial LOC counter reported `tools/nautilus` as "0 LOC" — this was a glob artifact (flat-dir files not matched), **not** missing code. Corrected; no real discrepancy. |
| Live-path coupling | **VERIFIED** | `trading/live_paper_runner.py` directly imports `decision.consensus_voting` (line 52) and live-wires HMM (lines ~516–611) + the XGBoost ML gate. These are NON-alpha but LOAD-BEARING — they must be excised from the runner before any deletion. |

---

## 2. What was deleted / archived / kept

**FINAL STATE: nothing was changed.** The audit produced an APPROVED plan; no
files were moved. The repo tree is unchanged from session start.

Approved plan (PENDING execution, in this order — excise-from-runner first):

- **KEEP** (research-critical, verified present): `tools/nautilus/` (harness),
  `tools/backtest/fetch_perp_data.py`, `tools/graduation/gate.py`,
  `risk/engine.py`, `risk/position_sizer.py`, `execution/idempotency.py`,
  `scripts/box/aaats-t3-oi-collector.py`, the parquet store under
  `data/historical/`.
- **DELETE** (~13.7k LOC dead/non-alpha): `v6-stack/`, `streamlit_app/`,
  `markets/india/`, `markets/us/`, `engine/`, `learning/`, `decision/`, root
  `*_COMPLETE.md` (6 files), `trading/{stat_arb,bollinger_range,momentum_breakout,funding_arb}.py`.
  **Order:** excise `consensus_voting`/HMM/XGBoost from `live_paper_runner.py`
  FIRST (after capturing a one-cycle baseline test), then delete.
- **ARCHIVE** (do not delete — retest-eligible): `trading/altcoin_reversion.py`
  (C3 — retest allowed ONLY on perps with funding-aware entry), `.rollback/`.
- **ml/**: ARCHIVE not delete (optionality; out of live path; returns only via
  a registered thesis proving predictive value).
- **markets/crypto/**: import-trace then SPLIT — keep data/FAPI primitives,
  delete strategy-coupled allocator/scanner after excision.

---

## 3. Realistic fill model

**STATUS: DOES NOT EXIST YET. This is the top PENDING P0.**

- **Current (asymmetric) model:** the harness prices fills as daily-close marks
  with a flat taker fee (`FEE_RATE = 0.0005`, 5 bps/side) inside
  [tools/nautilus/basket_ledger.py](../../tools/nautilus/basket_ledger.py)
  `simulate_basket(...)`. No spread, no participation cap, no impact. This can
  only produce false positives — a PASS under it is NOT trustworthy.
- **Where it will live:** grafted into `basket_ledger.simulate_basket` (or a
  thin wrapper it calls), so every existing and future thesis runner inherits
  it with no per-thesis change.
- **Scope (good-enough, ~1 day — do NOT gold-plate):**
  (a) spread term, (b) volume-participation cap, (c) OI-depth-keyed impact term.
  Bar is "stops flattering," not production-grade.
- **How to call it:** unchanged for callers — `simulate_basket(...)` gains the
  realistic cost internally; runners keep calling it as today.

Until this exists, **no thesis verdict is a trustworthy PASS**, regardless of
the 5-part gate.

---

## 4. Theses tested (verdicts on file)

None were run THIS session. The following are PRIOR verdicts already committed
to `data/graduation/`. **All used the current (asymmetric) fill model**, so
even the closest-to-passing are not trustworthy PASSes.

| Thesis | Verdict | pooled-OOS daily Sharpe | null empirical p | worst-fold DD | criteria missed | params-hash | One-line reason |
|---|---|---|---|---|---|---|---|
| T1 funding dispersion (`T1_funding_dispersion_PRECHECK_2026-06-06.json`) | **ECONOMICALLY_VOID** | n/a (killed at pre-check) | n/a | n/a | economics pre-check | not recorded* | Median round-trip funding income 8.68 bps < 10 bps round-trip taker — fee-dead before any PnL run. |
| T2 cross-sectional momentum (`T2_xsect_momentum_2026-06-06.json`) | **FAIL (NO-GO)** | 0.8572 (thr 1.0) | 0.043 (vs Bonferroni p97.5 thr 0.9576) | 0.7388 | 2,3,4,5 | not recorded* | 1/5 criteria met; pooled Sharpe below 1.0, fails Bonferroni null, 74% worst-fold DD. |
| Track F C3+TSMOM ensemble (2026-05-30) | **NO-GO** | see decision doc (NOT re-run this session) | decisive (documented) | — | 4/5 | not recorded* | Documented final arbiter: OOS indistinguishable from random signs. **Not independently re-derived yet.** |
| C1/C2/C3/C6/C5b/C7/TSMOM (2026-05-27→30) | **FAIL/NO-GO** | various, in `data/graduation/*.json` | various | — | various | not recorded* | Every public-kline directional class failed OOS. Do not revive (C3 perp-retest only). |

\* **params-hash is not recorded** — the field is introduced by the PENDING
Phase 2 ledger and does not exist in the current verdict JSONs.

---

## 5. Thesis workflow (how to test a new hypothesis)

The pipeline already exists as a code convention. A new thesis = copy a
template runner, swap one signal function, run two commands.

1. **Register** — copy the pre-registration template to
   `research/theses/T<n>_<name>.md` (template is PENDING creation in Phase 2),
   freeze the hypothesis + the 5 acceptance criteria + null model.
2. **Implement** — copy [tools/nautilus/run_t1_funding_dispersion.py](../../tools/nautilus/run_t1_funding_dispersion.py)
   to `run_t<n>_<name>.py`; replace **only** the signal function /
   schedule-builder (add it to `tools/nautilus/xsect_signals.py`). Inherited
   unchanged: `u30_data` loaders, `basket_ledger.simulate_basket`,
   `null_engines.null_distribution`, `xsect_walkforward.evaluate`.
3. **Run:**
   ```
   .venv-nt/Scripts/python tools/nautilus/run_t<n>_<name>.py --mode precheck   # economics gate (free, data-only)
   .venv-nt/Scripts/python tools/nautilus/run_t<n>_<name>.py --mode run        # walk-forward + null -> verdict JSON
   ```
   Verdict JSON lands in `data/graduation/`. The frozen 5-part gate
   (`xsect_walkforward.evaluate`): (1) ≥60% folds net>0, (2) median fold OOS
   Sharpe ≥0.5, (3) pooled-OOS daily Sharpe ≥1.0, (4) worst-fold maxDD ≤20%,
   (5) pooled Sharpe > registered null percentile (p95 single / p97.5
   Bonferroni for co-registered theses). ALL FIVE required; 4/5 = FAIL.
4. **Log** — append one line to `research/LEDGER.md` (PENDING creation).

**Canonical data panel (loads in <5 lines, exists today for funding/price):**
```python
uni     = u30_data.load_universe()
members = u30_data.membership_by_date(uni)        # point-in-time U30, no survivorship bias
symbols = u30_data.union_symbols(uni)
close   = u30_data.load_daily_close_panel(symbols)
funding = u30_data.load_funding(symbols)
```
OI / liquidations / basis loaders are NOT yet in `u30_data` (Phase 3 gap).

**Per-thesis discipline:** one registered NO-GO = archive the thesis. NO
re-tuning, NO "improving" a dead thesis. Next thesis gets a fresh
minimum-changes budget, never a fresh framework budget.

---

## 6. What's next

In execution order (the critical rule: ≤3 days total on framework before the
first new thesis is under test):

1. **Independently re-derive the 2026-05-30 NO-GO** (P0) — run
   `run_walk_forward.py` against `data/historical/*_contig` parquets; confirm
   NO-GO replicates; report any discrepancy. Needs the `.venv-nt` env present.
2. **Build the realistic fill model** (P0, ~1 day) — spread + participation
   cap + OI-depth impact, in `basket_ledger.simulate_basket`. Free/local.
3. **Phase 3 — structural-flow data readiness** — audit
   `scripts/box/aaats-t3-oi-collector.py` + FAPI fetchers; report
   collected-vs-missing for OI / funding / liquidations / long-short ratio /
   basis / premium index from **free** Binance/FAPI only. Flag any
   paid-data-gated signal and deprioritize that thesis.
4. **Next untested thesis — Funding-rate TIMING** (positioning extremes as a
   contrarian/momentum TRIGGER, NOT carry — carry is fee-dead, see T1).
   - Needs: funding level + history (HAVE), the realistic fill model (PENDING),
     a trigger signal in `xsect_signals.py`, a `run_t4_funding_timing.py`.
   - Then: Liquidation cascades (needs sub-15-min liq feed — feasibility TBD in
     Phase 3), then OI crowding (T3 — rank last if it needs paid history).

---

## 7. Repo status

- **Public:** YES. `github.com/Puneethmp/AAATS` is PUBLIC (`isPrivate: false`).
- **Committed secrets:** NONE. Full `git rev-list --all` scan found no live
  `.env` ever committed; `.gitignore` excludes `.env`/`*.env`/`secrets/`; no
  live secret patterns (Telegram/Binance/AWS/PEM) in tracked HEAD. The
  "secrets in `.env`" risk is contained to the box/local, never to git.
- **Re-privatization:** NOT DONE. It is the PASS-TRIGGERED action — the first
  step the moment a registered thesis PASSES walk-forward + null under the
  realistic fill model. No thesis has passed; therefore no re-privatization and
  no spend.
- **Commit posture while public:** commit nothing that adds NEW sensitive
  detail (secrets, IPs, topology). This handover deliberately contains none.

---

*Generated 2026-06-09. Reflects state after Phase 1 audit + Phase 2 design;
no implementation performed. Uncommitted at time of writing.*
