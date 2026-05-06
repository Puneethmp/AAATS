"""
Full Performance Attribution Engine
=====================================
Why this exists
---------------
Without proper attribution you cannot tell skill from luck, or identify
whether returns come from beta, factor tilts, or genuine alpha. This module
provides everything a quant shop needs to understand and report performance.

Contents
--------
  compute_metrics()           — Sharpe, Sortino, Calmar, Omega, IR, tail ratios
  brinson_attribution()       — Brinson-Hood-Beebower 3-effect decomposition
                                (allocation, selection, interaction)
  factor_attribution()        — OLS factor regression (market, SMB, HML, MOM)
  rolling_metrics()           — Rolling Sharpe/Sortino/drawdown over a window
  monte_carlo_sharpe()        — Bootstrap distribution of Sharpe ratio to
                                assess statistical confidence
  drawdown_analysis()         — Per-drawdown episode: depth, duration, recovery
  performance_report()        — Consolidated dict ready for logging / JSON export

Brinson-Hood-Beebower (1986)
-----------------------------
  Total active return = Allocation effect + Selection effect + Interaction effect

  Allocation  = Σ (w_p - w_b) × (R_b_i - R_b)
  Selection   = Σ w_b × (R_p_i - R_b_i)
  Interaction = Σ (w_p - w_b) × (R_p_i - R_b_i)

  where w_p = portfolio weight, w_b = benchmark weight,
        R_p_i = portfolio sector return, R_b_i = benchmark sector return.
"""

from __future__ import annotations

import warnings
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats

__all__ = [
    "compute_metrics",
    "brinson_attribution",
    "factor_attribution",
    "rolling_metrics",
    "monte_carlo_sharpe",
    "drawdown_analysis",
    "performance_report",
]

# ---------------------------------------------------------------------------
# Annualisation factors
# ---------------------------------------------------------------------------
_ANN = {"1min": 252 * 390, "5min": 252 * 78, "15min": 252 * 26,
        "1h": 252 * 6.5, "1Hour": 252 * 6.5, "1d": 252, "1Day": 252, "1w": 52}


def _ann_factor(freq: str) -> float:
    return _ANN.get(freq, 252)


# ---------------------------------------------------------------------------
# Core Metrics
# ---------------------------------------------------------------------------
def compute_metrics(
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    freq: str = "1d",
    risk_free_rate: float = 0.05,
) -> dict:
    """
    Compute the full set of single-strategy performance metrics.

    Parameters
    ----------
    returns           Daily (or per-bar) strategy returns.
    benchmark_returns Optional benchmark returns (same frequency).
    freq              Bar frequency for annualisation.
    risk_free_rate    Annual risk-free rate (default 5%).

    Returns
    -------
    dict with all metrics.
    """
    ann = _ann_factor(freq)
    rf_per_bar = (1 + risk_free_rate) ** (1 / ann) - 1
    r = returns.dropna()
    n = len(r)

    if n < 2:
        warnings.warn("Insufficient data for metric computation.", stacklevel=2)
        return {}

    excess = r - rf_per_bar
    total_ret = (1 + r).prod() - 1
    ann_ret = (1 + total_ret) ** (ann / n) - 1
    ann_vol = r.std() * np.sqrt(ann)
    sharpe = excess.mean() / r.std() * np.sqrt(ann) if r.std() > 0 else 0.0

    # Sortino — downside vol only
    downside = r[r < rf_per_bar]
    downside_vol = downside.std() * np.sqrt(ann) if len(downside) > 1 else np.nan
    sortino = (ann_ret - risk_free_rate) / downside_vol if (downside_vol and downside_vol > 0) else 0.0

    # Calmar
    equity = (1 + r).cumprod()
    max_dd = ((equity - equity.cummax()) / equity.cummax()).min()
    calmar = ann_ret / abs(max_dd) if max_dd < 0 else np.nan

    # Omega ratio
    threshold = rf_per_bar
    gains = r[r > threshold] - threshold
    losses = threshold - r[r <= threshold]
    omega = gains.sum() / losses.sum() if losses.sum() > 0 else np.inf

    # Tail ratio (95th / 5th percentile of absolute returns)
    tail_ratio = abs(np.percentile(r, 95)) / abs(np.percentile(r, 5)) if np.percentile(r, 5) != 0 else np.nan

    # Skewness and kurtosis
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r))  # excess kurtosis

    # Value at Risk and CVaR (95%)
    var_95 = float(np.percentile(r, 5))
    cvar_95 = float(r[r <= var_95].mean())

    # Win/loss
    wins = (r > 0).sum()
    win_rate = wins / n
    avg_win = r[r > 0].mean() if wins > 0 else 0.0
    avg_loss = r[r <= 0].mean() if (n - wins) > 0 else 0.0
    profit_factor = (r[r > 0].sum() / abs(r[r <= 0].sum())
                     if r[r <= 0].sum() != 0 else np.inf)

    result = {
        "n_bars": n,
        "total_return_pct": round(total_ret * 100, 3),
        "ann_return_pct": round(ann_ret * 100, 3),
        "ann_volatility_pct": round(ann_vol * 100, 3),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "calmar_ratio": round(calmar, 4) if not np.isnan(calmar) else None,
        "omega_ratio": round(omega, 4) if not np.isinf(omega) else None,
        "tail_ratio": round(tail_ratio, 4) if not np.isnan(tail_ratio) else None,
        "max_drawdown_pct": round(max_dd * 100, 3),
        "var_95_pct": round(var_95 * 100, 4),
        "cvar_95_pct": round(cvar_95 * 100, 4),
        "skewness": round(skew, 4),
        "excess_kurtosis": round(kurt, 4),
        "win_rate_pct": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 4) if not np.isinf(profit_factor) else None,
        "avg_win_pct": round(avg_win * 100, 4),
        "avg_loss_pct": round(avg_loss * 100, 4),
    }

    if benchmark_returns is not None:
        bm = benchmark_returns.reindex(r.index).dropna()
        aligned = pd.concat([r, bm], axis=1, join="inner")
        aligned.columns = ["strat", "bench"]
        if len(aligned) > 10:
            cov_mat = np.cov(aligned["strat"], aligned["bench"])
            beta = cov_mat[0, 1] / max(cov_mat[1, 1], 1e-12)
            bm_ann = (1 + aligned["bench"].mean()) ** ann - 1
            alpha = ann_ret - beta * bm_ann
            active = aligned["strat"] - aligned["bench"]
            te = active.std() * np.sqrt(ann)
            ir = active.mean() / active.std() * np.sqrt(ann) if active.std() > 0 else 0.0
            corr = float(aligned.corr().iloc[0, 1])
            result.update({
                "alpha_ann_pct": round(alpha * 100, 4),
                "beta": round(beta, 4),
                "tracking_error_pct": round(te * 100, 4),
                "information_ratio": round(ir, 4),
                "correlation_to_benchmark": round(corr, 4),
            })

    return result


# ---------------------------------------------------------------------------
# Brinson-Hood-Beebower Attribution
# ---------------------------------------------------------------------------
def brinson_attribution(
    portfolio_weights: pd.Series,
    benchmark_weights: pd.Series,
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    sector_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Brinson-Hood-Beebower 3-effect decomposition.

    Parameters
    ----------
    portfolio_weights   pd.Series indexed by asset, portfolio weights [0,1].
    benchmark_weights   pd.Series indexed by asset, benchmark weights [0,1].
    portfolio_returns   pd.Series indexed by asset, portfolio asset returns.
    benchmark_returns   pd.Series indexed by asset, benchmark asset returns.
    sector_map          Optional dict {asset -> sector} for sector-level rollup.

    Returns
    -------
    DataFrame with columns: allocation, selection, interaction, total_active.
    Indexed by asset (or sector if sector_map provided).
    """
    assets = portfolio_weights.index.union(benchmark_weights.index)
    wp = portfolio_weights.reindex(assets, fill_value=0.0)
    wb = benchmark_weights.reindex(assets, fill_value=0.0)
    rp = portfolio_returns.reindex(assets, fill_value=0.0)
    rb = benchmark_returns.reindex(assets, fill_value=0.0)

    # Benchmark total return
    rb_total = (wb * rb).sum()

    allocation = (wp - wb) * (rb - rb_total)
    selection = wb * (rp - rb)
    interaction = (wp - wb) * (rp - rb)
    total_active = allocation + selection + interaction

    df = pd.DataFrame({
        "portfolio_weight": wp,
        "benchmark_weight": wb,
        "portfolio_return": rp,
        "benchmark_return": rb,
        "allocation": allocation,
        "selection": selection,
        "interaction": interaction,
        "total_active": total_active,
    })

    if sector_map:
        df["sector"] = df.index.map(sector_map)
        df = df.groupby("sector").agg({
            "portfolio_weight": "sum",
            "benchmark_weight": "sum",
            "allocation": "sum",
            "selection": "sum",
            "interaction": "sum",
            "total_active": "sum",
        })

    return df


# ---------------------------------------------------------------------------
# Factor Attribution (OLS regression)
# ---------------------------------------------------------------------------
def factor_attribution(
    returns: pd.Series,
    factors: pd.DataFrame,
    risk_free: pd.Series | float = 0.0,
) -> dict:
    """
    Regress strategy returns on factor returns to decompose alpha and betas.

    Parameters
    ----------
    returns     Strategy return series.
    factors     DataFrame where each column is a factor return series.
                Standard factors: MKT, SMB, HML, MOM (Fama-French + Carhart).
    risk_free   Risk-free rate series or scalar (same frequency as returns).

    Returns
    -------
    dict with: alpha (annualised), factor_betas, t_stats, p_values,
               r_squared, residual_vol, active_return.

    Note: Annualised alpha assumes daily returns. Adjust ann_factor for other freq.
    """
    r = returns.dropna()
    if isinstance(risk_free, (int, float)):
        rf = pd.Series(risk_free, index=r.index)
    else:
        rf = risk_free.reindex(r.index).fillna(0)

    excess = r - rf
    F = factors.reindex(r.index).dropna()
    aligned = pd.concat([excess, F], axis=1, join="inner").dropna()
    y = aligned.iloc[:, 0].values
    X = aligned.iloc[:, 1:].values
    n, k = X.shape

    # Add intercept
    X_const = np.column_stack([np.ones(n), X])
    coef, resid, _, _ = np.linalg.lstsq(X_const, y, rcond=None)
    alpha_daily = coef[0]
    betas = coef[1:]

    y_hat = X_const @ coef
    ss_res = ((y - y_hat) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # t-stats and p-values
    mse = ss_res / max(n - k - 1, 1)
    var_coef = mse * np.linalg.pinv(X_const.T @ X_const).diagonal()
    se = np.sqrt(np.maximum(var_coef, 0))
    t_stats = coef / se
    p_vals = 2 * stats.t.sf(np.abs(t_stats), df=n - k - 1)

    factor_names = list(aligned.columns[1:])
    ann = 252  # assumes daily

    return {
        "alpha_daily": float(alpha_daily),
        "alpha_annualised_pct": float(alpha_daily * ann * 100),
        "alpha_t_stat": float(t_stats[0]),
        "alpha_p_value": float(p_vals[0]),
        "factor_betas": dict(zip(factor_names, betas.tolist())),
        "factor_t_stats": dict(zip(factor_names, t_stats[1:].tolist())),
        "factor_p_values": dict(zip(factor_names, p_vals[1:].tolist())),
        "r_squared": float(r_sq),
        "residual_vol_ann_pct": float(np.sqrt(mse * ann) * 100),
        "n_observations": n,
    }


# ---------------------------------------------------------------------------
# Rolling Metrics
# ---------------------------------------------------------------------------
def rolling_metrics(
    returns: pd.Series,
    window: int = 60,
    freq: str = "1d",
    risk_free_rate: float = 0.05,
) -> pd.DataFrame:
    """
    Compute rolling Sharpe, Sortino, and drawdown over a sliding window.

    Returns a DataFrame with columns: sharpe, sortino, drawdown, volatility.
    """
    ann = _ann_factor(freq)
    rf_per_bar = (1 + risk_free_rate) ** (1 / ann) - 1
    r = returns.dropna()

    roll_mean = r.rolling(window).mean()
    roll_std = r.rolling(window).std()
    rolling_sharpe = (roll_mean - rf_per_bar) / roll_std * np.sqrt(ann)

    def _downside_vol(x: pd.Series) -> float:
        d = x[x < rf_per_bar]
        return d.std() if len(d) > 1 else np.nan

    rolling_downside = r.rolling(window).apply(_downside_vol, raw=False)
    rolling_sortino = (roll_mean - rf_per_bar) / rolling_downside * np.sqrt(ann)

    equity = (1 + r).cumprod()
    rolling_dd = (equity - equity.rolling(window).max()) / equity.rolling(window).max()

    return pd.DataFrame({
        "sharpe": rolling_sharpe,
        "sortino": rolling_sortino,
        "drawdown": rolling_dd,
        "volatility": roll_std * np.sqrt(ann),
    })


# ---------------------------------------------------------------------------
# Monte Carlo Sharpe Bootstrap
# ---------------------------------------------------------------------------
def monte_carlo_sharpe(
    returns: pd.Series,
    n_simulations: int = 10_000,
    freq: str = "1d",
    confidence: float = 0.95,
    seed: int = 42,
) -> dict:
    """
    Bootstrap the Sharpe ratio distribution.

    Resamples the return series with replacement N times and computes
    the Sharpe on each. Gives confidence intervals and the probability
    the true Sharpe is positive.

    Returns
    -------
    dict with: observed_sharpe, ci_lower, ci_upper, prob_positive,
               bootstrap_mean, bootstrap_std.
    """
    rng = np.random.default_rng(seed)
    ann = _ann_factor(freq)
    r = returns.dropna().values
    n = len(r)

    sharpes = np.empty(n_simulations)
    for i in range(n_simulations):
        sample = rng.choice(r, size=n, replace=True)
        s = sample.mean() / sample.std() * np.sqrt(ann) if sample.std() > 0 else 0.0
        sharpes[i] = s

    alpha = 1 - confidence
    ci_lo, ci_hi = np.percentile(sharpes, [alpha / 2 * 100, (1 - alpha / 2) * 100])
    obs = r.mean() / r.std() * np.sqrt(ann) if r.std() > 0 else 0.0

    return {
        "observed_sharpe": round(obs, 4),
        "bootstrap_mean_sharpe": round(float(sharpes.mean()), 4),
        "bootstrap_std_sharpe": round(float(sharpes.std()), 4),
        f"ci_{int(confidence*100)}_lower": round(float(ci_lo), 4),
        f"ci_{int(confidence*100)}_upper": round(float(ci_hi), 4),
        "prob_sharpe_positive": round(float((sharpes > 0).mean()), 4),
        "n_simulations": n_simulations,
    }


# ---------------------------------------------------------------------------
# Drawdown Analysis
# ---------------------------------------------------------------------------
def drawdown_analysis(returns: pd.Series) -> pd.DataFrame:
    """
    Identify and characterise each drawdown episode.

    Returns a DataFrame with one row per drawdown episode:
    start, trough, recovery, depth_pct, duration_bars, recovery_bars.
    """
    equity = (1 + returns.dropna()).cumprod()
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max

    episodes = []
    in_dd = False
    start = None
    peak_val = None

    for date, val in dd.items():
        if not in_dd and val < 0:
            in_dd = True
            start = date
            peak_val = float(roll_max.loc[date])
            trough_date = date
            trough_depth = val
        elif in_dd:
            if val < trough_depth:
                trough_depth = val
                trough_date = date
            if val >= -1e-6:  # recovered
                episodes.append({
                    "start": start,
                    "trough": trough_date,
                    "recovery": date,
                    "depth_pct": round(float(trough_depth) * 100, 3),
                    "duration_bars": (returns.index.get_loc(trough_date) -
                                      returns.index.get_loc(start)),
                    "recovery_bars": (returns.index.get_loc(date) -
                                      returns.index.get_loc(trough_date)),
                    "peak_equity": peak_val,
                })
                in_dd = False

    # Still in drawdown at end
    if in_dd and start is not None:
        episodes.append({
            "start": start,
            "trough": trough_date,
            "recovery": None,
            "depth_pct": round(float(trough_depth) * 100, 3),
            "duration_bars": (returns.index.get_loc(trough_date) -
                              returns.index.get_loc(start)),
            "recovery_bars": None,
            "peak_equity": peak_val,
        })

    return pd.DataFrame(episodes) if episodes else pd.DataFrame(
        columns=["start", "trough", "recovery", "depth_pct",
                 "duration_bars", "recovery_bars", "peak_equity"]
    )


# ---------------------------------------------------------------------------
# Consolidated Performance Report
# ---------------------------------------------------------------------------
def performance_report(
    returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    freq: str = "1d",
    risk_free_rate: float = 0.05,
    n_bootstrap: int = 5_000,
) -> dict:
    """
    Generate a consolidated performance report combining all metrics.

    Returns a nested dict suitable for JSON serialisation or dashboard display.
    """
    metrics = compute_metrics(returns, benchmark_returns, freq, risk_free_rate)
    dd_df = drawdown_analysis(returns)
    mc = monte_carlo_sharpe(returns, n_simulations=n_bootstrap, freq=freq)
    roll = rolling_metrics(returns, freq=freq, risk_free_rate=risk_free_rate)

    # Top-5 worst drawdowns
    worst_dds = []
    if not dd_df.empty:
        worst = dd_df.nsmallest(5, "depth_pct")
        worst_dds = worst[["start", "trough", "depth_pct",
                            "duration_bars", "recovery_bars"]].to_dict("records")

    return {
        "summary": metrics,
        "worst_drawdowns": worst_dds,
        "sharpe_bootstrap": mc,
        "rolling_latest": {
            "sharpe_60": round(float(roll["sharpe"].iloc[-1]), 3)
            if not roll["sharpe"].iloc[-1:].isna().all() else None,
            "sortino_60": round(float(roll["sortino"].iloc[-1]), 3)
            if not roll["sortino"].iloc[-1:].isna().all() else None,
            "drawdown_pct": round(float(roll["drawdown"].iloc[-1]) * 100, 3)
            if not roll["drawdown"].iloc[-1:].isna().all() else None,
        },
    }
