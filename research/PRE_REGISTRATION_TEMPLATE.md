# Pre-Registration — T<N> <thesis short name>

> Copy this file to `research/theses/T<N>_<name>.md`, fill every `<...>`, then
> **commit it to origin/main BEFORE any signal/PnL computation.** The commit SHA
> is the registration timestamp (anti-snooping rule). One harness run per thesis,
> seed=7. A FAIL is terminal — no re-tuning, no "v2" of the same mechanism.

**STATUS:** `<DRAFT | REGISTERED (commit <sha>) | RUN (verdict <PASS|FAIL>)>`

## 1. Economic mechanism
<Why an edge should exist — the structural reason, not a backtest. One paragraph.
State explicitly how it differs from the closed boundary (own-price OHLCV
directional signals on majors at 1h–14d; carry; the C1/C2/C3/C6/C7/TSMOM set).>

## 2. Data (must be free/local)
- **Universe:** <e.g. point-in-time U30 — `u30_data.load_universe`>
- **Fields:** <funding / OHLCV / OI / liq / basis — and where each loads from>
- **Window:** <e.g. 2023-05-28 → 2026-05-27 (36mo, Track F window)>
- **Source:** <existing parquet store / free Binance-FAPI endpoint — name it>
- **Paid data required?** <NO — if YES, this thesis is deprioritized, not run>

## 3. Signal & portfolio (FROZEN)
<Exact signal definition, lookback, rank/threshold, rebalance cadence,
hysteresis, max hold, sizing. Frozen at registration — any change before the run
voids registration; any change after a FAIL is a NEW thesis.>

## 4. Fill model & fees (FROZEN)
- **Fees:** <taker 5bps/side unless registered otherwise>
- **Fill model:** `basket_ledger.simulate_basket` realistic model
  (spread + participation cap + OI-depth impact). **A PASS under the flat-fee /
  daily-close model is NOT trustworthy — name which model this run uses.**

## 5. Acceptance gate (5-part, frozen — `xsect_walkforward.evaluate`)
All five required; 4/5 = FAIL; no partial credit, no re-runs.
1. OOS net > 0 in ≥ 60% of folds
2. median per-fold OOS Sharpe ≥ 0.50 (per-trade, √60)
3. pooled-OOS daily Sharpe ≥ 1.0 (√365)
4. worst single-fold maxDD ≤ 20%
5. **null control:** pooled-OOS Sharpe > the registered null percentile
   (p95 single thesis / **p97.5** Bonferroni if co-registered), 1000 draws, seed=7

- **Walk-forward geometry:** 4mo train / 2mo OOS / 2mo step, anchored,
  non-overlapping OOS, ≥15 folds (`xsect_walkforward.make_folds`).
- **Null model (frozen):** <selection-shuffle preserving dates/counts/turnover —
  name it; `null_engines.null_distribution`>
- **Economics pre-check (optional, data-only, allowed before the run):**
  <e.g. median selected-name funding income vs round-trip taker cost; VOID =
  terminal, same standing as FAIL. The single permitted look at data pre-run.>

## 6. Pass / kill criteria
- **PASS:** all 5 met → STOP, report verdict + null p-value + params-hash;
  recommend re-privatize repo + begin realistic-fill forward soak. No live capital.
- **KILL (default):** one registered NO-GO/VOID → archive the thesis. Do NOT
  re-tune. Next thesis gets a fresh minimum-changes budget, never a new framework.

## 7. Run record (filled after the run)
- Command: `.venv-nt/Scripts/python tools/nautilus/run_t<N>_<name>.py --mode run`
- Verdict JSON: `data/graduation/<file>.json`
- params-hash: `<from research/log_verdict.py>`
- Ledger line appended: `<yes/no>`
