"""Shared walk-forward gate for the cross-sectional reactivation theses (T1/T2).

Implements the FROZEN 5-part acceptance criterion from
docs/decisions/2026-06-06_reactivation_thesis_portfolio_preregistration.md §3,
reused verbatim from the Track F walk-forward (tools/nautilus/run_walk_forward.py)
with one registered change: the null threshold is the **97.5th** percentile
(Bonferroni for the two simultaneously-registered theses T1+T2), not the 95th.

Fold geometry (identical to Track F): 4mo train / 2mo OOS / 2mo step, anchored,
non-overlapping OOS, >=15 folds over the 36-month window.

Both theses score against a BasketResult (per-trade ledger + daily PnL) from
basket_ledger.simulate_basket and a null distribution of pooled-OOS daily Sharpes
from null_engines. The gate is all-or-nothing: ALL FIVE required, 4/5 = FAIL.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

ANN_DAILY = float(np.sqrt(365.0))  # 24/7-crypto daily annualization (criteria 3 & 5)
ANN_TRADE = float(np.sqrt(60.0))  # per-trade convention (criterion 2), Track-F family
TRAIN_MO, OOS_MO, STEP_MO = 4, 2, 2
NULL_PCTL = 97.5  # Bonferroni p97.5 (two theses)


def sharpe(returns, ann: float) -> float:
    r = np.asarray(returns, dtype=float)
    if len(r) < 2 or r.std(ddof=1) <= 1e-12:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * ann)


def make_folds(start: pd.Timestamp, end: pd.Timestamp):
    """Anchored, non-overlapping 2mo OOS folds (4mo train, 2mo step)."""
    folds = []
    lo = start + pd.DateOffset(months=TRAIN_MO)
    while lo + pd.DateOffset(months=OOS_MO) <= end:
        hi = lo + pd.DateOffset(months=OOS_MO)
        folds.append((lo, hi))
        lo = lo + pd.DateOffset(months=STEP_MO)
    return folds


def _trades_in(trades, lo, hi):
    loi, hii = int(lo.value), int(hi.value)
    return [t for t in trades if loi <= t["ts"] < hii]


def fold_maxdd(daily_pnl: pd.Series, lo, hi, book: float) -> float:
    seg = daily_pnl[(daily_pnl.index >= lo) & (daily_pnl.index < hi)]
    if seg.empty:
        return 0.0
    eq = book + np.cumsum(seg.to_numpy())
    peak = np.maximum.accumulate(eq)
    return float(np.max((peak - eq) / peak)) if len(eq) else 0.0


def pooled_oos_daily_sharpe(daily_pnl: pd.Series, folds, book: float) -> float:
    """Daily Sharpe on the concatenation of all OOS-window daily returns."""
    mask = np.zeros(len(daily_pnl), dtype=bool)
    idx = daily_pnl.index
    for lo, hi in folds:
        mask |= (idx >= lo) & (idx < hi)
    rets = (daily_pnl[mask] / book).to_numpy()
    return sharpe(rets, ANN_DAILY)


def evaluate(result, folds, null_sharpes: np.ndarray) -> dict:
    """Score the frozen 5-part criterion. `result` is a BasketResult; `folds` the
    OOS windows; `null_sharpes` the pooled-OOS daily Sharpe under the registered
    null (1000 draws). Returns a fully-populated verdict dict (committed verbatim)."""
    trades, daily_pnl, book = result.trades, result.daily_pnl, result.book

    fold_rows = []
    fold_nets, fold_sharpes, fold_dds = [], [], []
    for i, (lo, hi) in enumerate(folds):
        tf = _trades_in(trades, lo, hi)
        net = float(sum(t["pnl_net"] for t in tf))
        rets = [t["pnl_net"] / t["notional"] for t in tf if t["notional"] > 0]
        fsh = sharpe(rets, ANN_TRADE)
        dd = fold_maxdd(daily_pnl, lo, hi, book)
        fold_nets.append(net)
        fold_sharpes.append(fsh)
        fold_dds.append(dd)
        fold_rows.append(
            {
                "fold": i,
                "oos": f"{lo.date()}->{hi.date()}",
                "n_trades": len(tf),
                "net_usd": round(net, 4),
                "fold_sharpe": round(fsh, 4),
                "maxdd_pct": round(dd, 4),
            }
        )

    frac_pos = float(np.mean([n > 0 for n in fold_nets])) if fold_nets else 0.0
    med_sharpe = float(np.median(fold_sharpes)) if fold_sharpes else 0.0
    worst_dd = float(np.max(fold_dds)) if fold_dds else 0.0
    pooled_sharpe = pooled_oos_daily_sharpe(daily_pnl, folds, book)

    null_thresh = (
        float(np.percentile(null_sharpes, NULL_PCTL))
        if len(null_sharpes)
        else float("inf")
    )
    null_p_emp = (
        float(np.mean(null_sharpes >= pooled_sharpe)) if len(null_sharpes) else 1.0
    )

    oos_trades = [t for (lo, hi) in folds for t in _trades_in(trades, lo, hi)]
    n_oos_trades = len(oos_trades)

    c1 = frac_pos >= 0.60
    c2 = med_sharpe >= 0.50
    c3 = pooled_sharpe >= 1.0
    c4 = worst_dd <= 0.20
    c5 = pooled_sharpe > null_thresh
    passed = c1 and c2 and c3 and c4 and c5

    return {
        "verdict": "PASS" if passed else "FAIL",
        "passed": passed,
        "criteria": {
            "1_frac_folds_net_pos": {
                "value": round(frac_pos, 4),
                "threshold": 0.60,
                "passed": c1,
            },
            "2_median_fold_oos_sharpe": {
                "value": round(med_sharpe, 4),
                "threshold": 0.50,
                "passed": c2,
            },
            "3_pooled_oos_daily_sharpe": {
                "value": round(pooled_sharpe, 4),
                "threshold": 1.0,
                "passed": c3,
            },
            "4_worst_fold_maxdd": {
                "value": round(worst_dd, 4),
                "threshold": 0.20,
                "passed": c4,
            },
            "5_null_control": {
                "pooled_oos_daily_sharpe": round(pooled_sharpe, 4),
                "null_pctl": NULL_PCTL,
                "null_threshold": round(null_thresh, 4),
                "null_empirical_p": round(null_p_emp, 5),
                "null_mean": round(float(np.mean(null_sharpes)), 4)
                if len(null_sharpes)
                else None,
                "null_std": round(float(np.std(null_sharpes)), 4)
                if len(null_sharpes)
                else None,
                "passed": c5,
            },
        },
        "n_folds": len(folds),
        "n_oos_trades": n_oos_trades,
        "fold_detail": fold_rows,
        "fees_total_usd": round(result.fees_total_usd, 4),
        "funding_total_usd": round(result.funding_total_usd, 4),
        "criteria_missed": [
            k for k, ok in zip("12345", [c1, c2, c3, c4, c5]) if not ok
        ],
    }
