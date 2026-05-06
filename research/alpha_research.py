"""
Alpha Research Infrastructure
==============================
Why this exists
---------------
Before deploying any signal live, you must answer three questions:
  1. Is the signal predictive at all?   → Information Coefficient (IC)
  2. Is the predictive power consistent? → Information Ratio (IR)
  3. How fast does the edge decay?       → Alpha Decay Analysis

If IC is not significantly different from zero, your strategy is noise.
If IR is below ~0.5 your signal is too noisy to use reliably.
If alpha decays in 1 bar, you need intraday execution; if it lasts weeks,
you have more room for daily rebalancing.

Contents
--------
  compute_ic()            — Spearman / Pearson IC between signal and forward returns
  compute_ir()            — IC / IC_std (the key quality ratio)
  alpha_decay()           — IC at lags 1..N to see how fast signal fades
  quantile_returns()      — Sort assets into N quantiles by signal; compare returns
  factor_turnover()       — Signal autocorrelation = implied portfolio churn
  signal_autocorrelation()— Raw ACF of the signal
  alpha_summary()         — Consolidated analysis dict

Reference
---------
  Grinold & Kahn, "Active Portfolio Management" (2nd ed.)
  Prado, "Advances in Financial Machine Learning" (Ch. 3)
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats

__all__ = [
    "compute_ic",
    "compute_ir",
    "alpha_decay",
    "quantile_returns",
    "factor_turnover",
    "signal_autocorrelation",
    "alpha_summary",
]


# ---------------------------------------------------------------------------
# Information Coefficient
# ---------------------------------------------------------------------------
def compute_ic(
    signal: pd.Series,
    forward_returns: pd.Series,
    method: str = "spearman",
) -> float:
    """
    Compute the Information Coefficient between a signal and forward returns.

    IC = correlation between signal rank and forward return rank.

    Spearman (rank) IC is preferred because it is robust to outliers and
    does not assume a linear relationship.

    Parameters
    ----------
    signal          Signal values (higher = more bullish).
    forward_returns Returns measured N periods forward from the signal date.
    method          'spearman' (rank, robust) or 'pearson' (linear).

    Returns
    -------
    float: IC in [-1, 1]. |IC| > 0.05 is considered meaningful in practice.
    """
    aligned = pd.concat([signal, forward_returns], axis=1, join="inner").dropna()
    if len(aligned) < 5:
        return float("nan")
    s, f = aligned.iloc[:, 0], aligned.iloc[:, 1]
    if method == "spearman":
        ic, _ = stats.spearmanr(s, f)
    else:
        ic, _ = stats.pearsonr(s, f)
    return float(ic)


# ---------------------------------------------------------------------------
# Rolling IC + Information Ratio
# ---------------------------------------------------------------------------
def compute_ir(
    signal: pd.Series,
    forward_returns: pd.Series,
    window: int = 60,
    method: str = "spearman",
) -> dict:
    """
    Compute the rolling IC and aggregate Information Ratio.

    IR = mean(IC) / std(IC)  over the full sample.
    IR > 0.5 is the typical minimum bar for a deployable signal.

    Returns
    -------
    dict with: mean_ic, ic_std, ir, t_stat, p_value, rolling_ic (Series).
    """
    aligned = pd.concat([signal, forward_returns], axis=1, join="inner").dropna()
    if len(aligned) < window:
        warnings.warn("Insufficient data for rolling IC.", stacklevel=2)
        return {"mean_ic": float("nan"), "ir": float("nan"), "rolling_ic": pd.Series(dtype=float)}

    aligned.columns = ["signal", "fwd_ret"]

    # Rolling IC using Spearman on each window
    rolling_ic_vals = []
    dates = []
    for i in range(window, len(aligned) + 1):
        chunk = aligned.iloc[i - window: i]
        if method == "spearman":
            ic, _ = stats.spearmanr(chunk["signal"], chunk["fwd_ret"])
        else:
            ic, _ = stats.pearsonr(chunk["signal"], chunk["fwd_ret"])
        rolling_ic_vals.append(ic)
        dates.append(aligned.index[i - 1])

    rolling_ic = pd.Series(rolling_ic_vals, index=dates, name="rolling_ic")

    mean_ic = float(rolling_ic.mean())
    ic_std = float(rolling_ic.std())
    ir = mean_ic / ic_std if ic_std > 0 else 0.0
    n = len(rolling_ic)
    t_stat = ir * np.sqrt(n)
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)

    return {
        "mean_ic": round(mean_ic, 6),
        "ic_std": round(ic_std, 6),
        "ir": round(ir, 4),
        "t_stat": round(t_stat, 4),
        "p_value": round(p_val, 6),
        "n_windows": n,
        "rolling_ic": rolling_ic,
        "pct_positive_ic": round(float((rolling_ic > 0).mean() * 100), 2),
    }


# ---------------------------------------------------------------------------
# Alpha Decay Analysis
# ---------------------------------------------------------------------------
def alpha_decay(
    signal: pd.Series,
    returns: pd.Series,
    max_lag: int = 20,
    method: str = "spearman",
) -> pd.DataFrame:
    """
    Measure how IC changes as the holding period (lag) increases.

    A signal with IC that drops to zero after 2 bars requires high-frequency
    execution. A signal with IC still positive at lag 20 allows weekly rebalancing.

    Parameters
    ----------
    signal          Signal at each date.
    returns         Per-bar returns (used to construct compounded forward returns).
    max_lag         Maximum look-ahead horizon in bars.

    Returns
    -------
    DataFrame with columns: lag, ic, t_stat, p_value, significant.
    """
    rows = []
    for lag in range(1, max_lag + 1):
        # Compound forward return over `lag` bars
        fwd = returns.shift(-lag)
        # For multi-bar: rolling product of (1+r)
        if lag > 1:
            fwd_compound = (1 + returns).rolling(lag).apply(np.prod, raw=True).shift(-lag) - 1
        else:
            fwd_compound = fwd

        aligned = pd.concat([signal, fwd_compound], axis=1, join="inner").dropna()
        n = len(aligned)
        if n < 10:
            continue
        s, f = aligned.iloc[:, 0].values, aligned.iloc[:, 1].values
        if method == "spearman":
            ic, p = stats.spearmanr(s, f)
        else:
            ic, p = stats.pearsonr(s, f)
        t = ic * np.sqrt(n - 2) / np.sqrt(max(1 - ic**2, 1e-12))
        rows.append({
            "lag": lag,
            "ic": round(float(ic), 6),
            "t_stat": round(float(t), 4),
            "p_value": round(float(p), 6),
            "significant": p < 0.05,
            "n": n,
        })
    return pd.DataFrame(rows).set_index("lag") if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Quantile Return Analysis
# ---------------------------------------------------------------------------
def quantile_returns(
    signal: pd.Series,
    forward_returns: pd.Series,
    n_quantiles: int = 5,
) -> pd.DataFrame:
    """
    Divide assets (or time periods) into N quantiles by signal strength
    and compare the forward returns across quantiles.

    The spread between Q1 and Q5 (long-short) is the theoretical alpha
    available from the signal before costs.

    Parameters
    ----------
    signal          Signal values.
    forward_returns Forward returns (same index as signal).
    n_quantiles     Number of buckets (5 = quintiles, 10 = deciles).

    Returns
    -------
    DataFrame indexed by quantile (1 = lowest signal, N = highest):
    mean_return, median_return, std_return, sharpe, n_obs.
    """
    aligned = pd.concat([signal, forward_returns], axis=1, join="inner").dropna()
    aligned.columns = ["signal", "fwd_ret"]
    aligned["quantile"] = pd.qcut(
        aligned["signal"], q=n_quantiles, labels=False, duplicates="drop"
    ) + 1

    result = aligned.groupby("quantile")["fwd_ret"].agg(
        mean_return="mean",
        median_return="median",
        std_return="std",
        n_obs="count",
    ).round(6)
    result["sharpe"] = (result["mean_return"] / result["std_return"]).round(4)
    result["mean_return_pct"] = (result["mean_return"] * 100).round(4)

    # Long-short spread (Q_top - Q_bottom)
    if len(result) >= 2:
        ls_return = result["mean_return"].iloc[-1] - result["mean_return"].iloc[0]
        result.attrs["long_short_return_pct"] = round(ls_return * 100, 4)
        result.attrs["spread_t_stat"] = float(
            stats.ttest_ind(
                aligned.loc[aligned["quantile"] == n_quantiles, "fwd_ret"],
                aligned.loc[aligned["quantile"] == 1, "fwd_ret"],
            ).statistic
        )

    return result


# ---------------------------------------------------------------------------
# Factor Turnover (signal autocorrelation → implied churn)
# ---------------------------------------------------------------------------
def factor_turnover(signal: pd.Series, lags: int = 10) -> pd.DataFrame:
    """
    Compute signal autocorrelation at lags 1..N.

    High autocorrelation at lag 1 → signal changes slowly → low turnover,
    lower transaction costs. Low autocorrelation → signal flips frequently
    → high turnover, costs dominate.

    Returns
    -------
    DataFrame with: lag, autocorrelation, implied_turnover_pct.
    implied_turnover_pct = (1 - autocorrelation) × 100.
    """
    rows = []
    s = signal.dropna()
    for lag in range(1, lags + 1):
        acf = float(s.autocorr(lag=lag))
        rows.append({
            "lag": lag,
            "autocorrelation": round(acf, 6),
            "implied_turnover_pct": round((1 - acf) * 100, 2),
        })
    return pd.DataFrame(rows).set_index("lag")


# ---------------------------------------------------------------------------
# Signal Autocorrelation (raw ACF)
# ---------------------------------------------------------------------------
def signal_autocorrelation(signal: pd.Series, nlags: int = 20) -> pd.Series:
    """
    Compute the raw autocorrelation function of the signal.

    Returns a Series indexed by lag with autocorrelation values.
    """
    s = signal.dropna()
    acf_vals = [s.autocorr(lag=i) for i in range(1, nlags + 1)]
    return pd.Series(acf_vals, index=range(1, nlags + 1), name="signal_acf")


# ---------------------------------------------------------------------------
# Consolidated Alpha Summary
# ---------------------------------------------------------------------------
def alpha_summary(
    signal: pd.Series,
    returns: pd.Series,
    forward_horizon: int = 1,
    ic_window: int = 60,
    n_quantiles: int = 5,
    max_decay_lag: int = 20,
) -> dict:
    """
    Run the full alpha research suite and return a single consolidated report.

    Parameters
    ----------
    signal           Signal series (e.g. from your strategy).
    returns          Per-bar return series.
    forward_horizon  Primary holding period for IC computation.
    ic_window        Rolling window for IR calculation.
    n_quantiles      Quantiles for spread analysis.
    max_decay_lag    Horizon for alpha decay curve.

    Returns
    -------
    dict with: ic_stats, quantile_spread, decay_summary, turnover, verdict.
    """
    # Forward returns
    fwd_ret = returns.shift(-forward_horizon)

    # IC
    ic_stats = compute_ir(signal, fwd_ret, window=ic_window)
    ic_val = ic_stats["mean_ic"]
    ir_val = ic_stats["ir"]

    # Quantile spread
    q_ret = quantile_returns(signal, fwd_ret, n_quantiles=n_quantiles)
    ls_spread = q_ret.attrs.get("long_short_return_pct", float("nan"))
    ls_tstat = q_ret.attrs.get("spread_t_stat", float("nan"))

    # Alpha decay — summarise half-life (lag where IC drops to 50% of lag-1)
    decay_df = alpha_decay(signal, returns, max_lag=max_decay_lag)
    half_life = None
    if not decay_df.empty and abs(ic_val) > 1e-6:
        target = abs(ic_val) * 0.5
        above = decay_df[decay_df["ic"].abs() >= target]
        if not above.empty:
            half_life = int(above.index.max())

    # Turnover
    to_df = factor_turnover(signal, lags=min(10, max_decay_lag))
    lag1_to = float(to_df["implied_turnover_pct"].iloc[0]) if not to_df.empty else float("nan")

    # Verdict
    deployable = (
        abs(ir_val) >= 0.5
        and ic_stats.get("p_value", 1.0) < 0.05
        and not np.isnan(ls_spread)
        and abs(ls_spread) > 0
    )

    return {
        "signal_name": signal.name or "unknown",
        "forward_horizon_bars": forward_horizon,
        "ic_stats": {k: v for k, v in ic_stats.items() if k != "rolling_ic"},
        "quantile_analysis": {
            "n_quantiles": n_quantiles,
            "long_short_spread_pct": ls_spread,
            "long_short_t_stat": round(ls_tstat, 4) if not np.isnan(ls_tstat) else None,
        },
        "alpha_decay": {
            "half_life_bars": half_life,
            "ic_at_lag_1": round(float(decay_df["ic"].iloc[0]), 6) if not decay_df.empty else None,
            "ic_still_significant_at": int(decay_df[decay_df["significant"]].index.max())
            if not decay_df.empty and decay_df["significant"].any() else 0,
        },
        "turnover": {
            "lag1_autocorrelation": round(1 - lag1_to / 100, 4),
            "implied_daily_turnover_pct": round(lag1_to, 2),
        },
        "verdict": {
            "deployable": deployable,
            "reason": (
                "Signal passes IC/IR/spread thresholds."
                if deployable
                else f"IR={ir_val:.3f} (need ≥0.5), p={ic_stats.get('p_value', 1.0):.4f} "
                     f"(need <0.05). Do not deploy."
            ),
        },
    }
