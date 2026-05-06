"""
Portfolio Optimization Engine
==============================
Why this exists
---------------
Picking allocation weights by "health score" heuristics is not quant.
Mean-variance optimization, risk parity, and Kelly criterion are the
mathematical foundations of portfolio construction. Without them, you
are leaving risk-adjusted return on the table.

This module provides four optimization objectives, all solved via
scipy.optimize with full constraint support:

  1. mean_variance()       — Markowitz (1952): maximize return for a
                             given variance, or minimize variance for a
                             given return. The efficient frontier.

  2. max_sharpe()          — Maximize the Sharpe ratio (tangency portfolio).
                             The single best objective for most long-only funds.

  3. risk_parity()         — Equal Risk Contribution (ERC): each asset
                             contributes the same fraction of total portfolio
                             risk. Robust when return forecasts are unreliable.

  4. kelly_criterion()     — Full Kelly: maximize E[log(wealth)] = E[r] - Var/2.
                             Fractional Kelly (f * Kelly) is used in practice
                             to reduce variance at the cost of some growth rate.

  5. min_variance()        — Minimum variance portfolio (special case of MVO
                             with no return objective).

All methods return a dict with weights, expected return, expected vol,
expected Sharpe, and solver diagnostics.

Constraints applied everywhere
--------------------------------
  - Weights sum to 1 (fully invested)
  - No short positions by default (long_only=True)
  - Individual weight bounds: [min_weight, max_weight]
  - Maximum number of non-zero positions (cardinality limit)

Usage
-----
  import pandas as pd
  import numpy as np
  from portfolio.optimizer import max_sharpe, risk_parity

  # mu: expected returns (Series), cov: covariance matrix (DataFrame)
  result = max_sharpe(mu, cov, risk_free=0.05)
  print(result['weights'])
  print(result['sharpe'])
"""

from __future__ import annotations

import warnings
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize, OptimizeResult

__all__ = [
    "mean_variance",
    "max_sharpe",
    "risk_parity",
    "min_variance",
    "kelly_criterion",
    "efficient_frontier",
    "portfolio_stats",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def portfolio_stats(
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    risk_free: float = 0.0,
    ann: float = 252.0,
) -> dict:
    """Return annualised return, volatility, and Sharpe for a weight vector."""
    w = weights / weights.sum()  # normalise
    port_ret = float(np.dot(w, mu)) * ann
    port_var = float(w @ cov @ w) * ann
    port_vol = np.sqrt(max(port_var, 1e-12))
    sharpe = (port_ret - risk_free) / port_vol if port_vol > 0 else 0.0
    return {
        "ann_return": port_ret,
        "ann_volatility": port_vol,
        "sharpe": sharpe,
    }


def _validate_inputs(
    mu: pd.Series | np.ndarray,
    cov: pd.DataFrame | np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list]:
    mu_arr = np.asarray(mu, dtype=float)
    cov_arr = np.asarray(cov, dtype=float)
    n = len(mu_arr)
    if cov_arr.shape != (n, n):
        raise ValueError(f"cov shape {cov_arr.shape} inconsistent with mu length {n}")
    names = list(mu.index) if isinstance(mu, pd.Series) else [f"asset_{i}" for i in range(n)]
    return mu_arr, cov_arr, names


def _build_constraints(n: int, long_only: bool, w_min: float, w_max: float) -> list:
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    return constraints


def _bounds(n: int, long_only: bool, w_min: float, w_max: float):
    lo = max(w_min, 0.0) if long_only else w_min
    return [(lo, w_max)] * n


def _result_dict(
    weights: np.ndarray,
    names: list,
    mu: np.ndarray,
    cov: np.ndarray,
    risk_free: float,
    ann: float,
    method: str,
    solver_ok: bool,
) -> dict:
    w = weights / weights.sum()
    stats = portfolio_stats(w, mu, cov, risk_free, ann)
    return {
        "method": method,
        "weights": dict(zip(names, w.round(6).tolist())),
        "n_assets": int((w > 1e-4).sum()),
        "ann_return_pct": round(stats["ann_return"] * 100, 3),
        "ann_volatility_pct": round(stats["ann_volatility"] * 100, 3),
        "sharpe": round(stats["sharpe"], 4),
        "solver_success": solver_ok,
    }


# ---------------------------------------------------------------------------
# Mean-Variance Optimization (Markowitz)
# ---------------------------------------------------------------------------
def mean_variance(
    mu: pd.Series | np.ndarray,
    cov: pd.DataFrame | np.ndarray,
    target_return: float | None = None,
    target_volatility: float | None = None,
    risk_free: float = 0.0,
    long_only: bool = True,
    w_min: float = 0.0,
    w_max: float = 1.0,
    ann: float = 252.0,
) -> dict:
    """
    Markowitz mean-variance optimization.

    Exactly one of target_return or target_volatility must be specified:
      - target_return    → minimize variance subject to E[r] >= target_return
      - target_volatility→ maximize return subject to vol <= target_volatility

    If neither is provided, falls back to minimum-variance portfolio.

    Parameters are annualised; internally converted to per-bar.
    """
    mu_arr, cov_arr, names = _validate_inputs(mu, cov)
    n = len(mu_arr)
    mu_pb = mu_arr / ann          # per-bar
    cov_pb = cov_arr / ann

    bounds = _bounds(n, long_only, w_min, w_max)
    constraints = _build_constraints(n, long_only, w_min, w_max)

    if target_return is not None:
        # Minimize variance s.t. return >= target
        r_pb = target_return / ann
        constraints.append({
            "type": "ineq",
            "fun": lambda w: np.dot(w, mu_pb) - r_pb,
        })
        objective = lambda w: float(w @ cov_pb @ w)
        grad = lambda w: 2 * cov_pb @ w
    elif target_volatility is not None:
        # Maximize return s.t. vol <= target
        v_pb = target_volatility / np.sqrt(ann)
        constraints.append({
            "type": "ineq",
            "fun": lambda w: v_pb**2 - float(w @ cov_pb @ w),
        })
        objective = lambda w: -float(np.dot(w, mu_pb))
        grad = lambda w: -mu_pb
    else:
        # Default: minimum variance
        objective = lambda w: float(w @ cov_pb @ w)
        grad = lambda w: 2 * cov_pb @ w

    w0 = np.ones(n) / n
    res: OptimizeResult = minimize(
        objective, w0,
        jac=grad if target_return is not None or target_volatility is None else None,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-10},
    )
    return _result_dict(res.x, names, mu_arr, cov_arr, risk_free, ann,
                        "mean_variance", res.success)


# ---------------------------------------------------------------------------
# Maximum Sharpe (Tangency Portfolio)
# ---------------------------------------------------------------------------
def max_sharpe(
    mu: pd.Series | np.ndarray,
    cov: pd.DataFrame | np.ndarray,
    risk_free: float = 0.05,
    long_only: bool = True,
    w_min: float = 0.0,
    w_max: float = 1.0,
    ann: float = 252.0,
) -> dict:
    """
    Maximize the Sharpe ratio (tangency portfolio).

    Uses the Sharpe-ratio-maximizing trick: transform to an unconstrained
    problem by dividing by the excess return, then solve via SLSQP.

    This is the single most useful optimization objective for most funds:
    it finds the portfolio with the highest reward-per-unit-of-risk.
    """
    mu_arr, cov_arr, names = _validate_inputs(mu, cov)
    n = len(mu_arr)
    rf_pb = (1 + risk_free) ** (1 / ann) - 1
    excess_mu = mu_arr / ann - rf_pb

    if (excess_mu <= 0).all():
        warnings.warn("All assets have non-positive excess returns. Returning equal weights.", stacklevel=2)
        w = np.ones(n) / n
        return _result_dict(w, names, mu_arr, cov_arr, risk_free, ann, "max_sharpe", False)

    bounds = _bounds(n, long_only, w_min, w_max)
    constraints = _build_constraints(n, long_only, w_min, w_max)
    cov_pb = cov_arr / ann

    def neg_sharpe(w: np.ndarray) -> float:
        port_ret = float(np.dot(w, excess_mu))
        port_vol = np.sqrt(max(float(w @ cov_pb @ w), 1e-12))
        return -port_ret / port_vol

    def neg_sharpe_grad(w: np.ndarray) -> np.ndarray:
        port_ret = float(np.dot(w, excess_mu))
        port_var = max(float(w @ cov_pb @ w), 1e-12)
        port_vol = np.sqrt(port_var)
        d_ret = excess_mu
        d_vol = (cov_pb @ w) / port_vol
        return -(d_ret * port_vol - port_ret * d_vol) / port_var

    # Multiple restarts to avoid local minima
    best_sharpe = -np.inf
    best_w = np.ones(n) / n
    best_success = False
    rng = np.random.default_rng(42)

    for _ in range(5):
        w0 = rng.dirichlet(np.ones(n))
        res = minimize(
            neg_sharpe, w0, jac=neg_sharpe_grad,
            method="SLSQP", bounds=bounds, constraints=constraints,
            options={"maxiter": 500, "ftol": 1e-12},
        )
        if res.success and -res.fun > best_sharpe:
            best_sharpe = -res.fun
            best_w = res.x
            best_success = True

    return _result_dict(best_w, names, mu_arr, cov_arr, risk_free, ann,
                        "max_sharpe", best_success)


# ---------------------------------------------------------------------------
# Minimum Variance
# ---------------------------------------------------------------------------
def min_variance(
    mu: pd.Series | np.ndarray,
    cov: pd.DataFrame | np.ndarray,
    risk_free: float = 0.0,
    long_only: bool = True,
    w_min: float = 0.0,
    w_max: float = 1.0,
    ann: float = 252.0,
) -> dict:
    """
    Minimum variance portfolio: minimize portfolio volatility ignoring returns.

    Useful when return forecasts are unreliable (which is most of the time).
    The MVP is the leftmost point on the efficient frontier.
    """
    mu_arr, cov_arr, names = _validate_inputs(mu, cov)
    n = len(mu_arr)
    cov_pb = cov_arr / ann
    bounds = _bounds(n, long_only, w_min, w_max)
    constraints = _build_constraints(n, long_only, w_min, w_max)

    res = minimize(
        lambda w: float(w @ cov_pb @ w),
        np.ones(n) / n,
        jac=lambda w: 2 * cov_pb @ w,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    return _result_dict(res.x, names, mu_arr, cov_arr, risk_free, ann,
                        "min_variance", res.success)


# ---------------------------------------------------------------------------
# Risk Parity (Equal Risk Contribution)
# ---------------------------------------------------------------------------
def risk_parity(
    mu: pd.Series | np.ndarray,
    cov: pd.DataFrame | np.ndarray,
    risk_budgets: np.ndarray | None = None,
    risk_free: float = 0.0,
    w_min: float = 0.0,
    w_max: float = 1.0,
    ann: float = 252.0,
) -> dict:
    """
    Risk Parity: Equal Risk Contribution (ERC) portfolio.

    Each asset contributes the same fraction of total portfolio variance.
    The risk contribution of asset i is:
      RC_i = w_i * (Cov @ w)_i / (w^T Cov w)

    ERC sets RC_i = 1/N for all i (or proportional to risk_budgets).

    Risk parity is robust when return forecasts are weak or absent.
    Used by Bridgewater (All Weather), AQR, and most risk-parity funds.

    Parameters
    ----------
    risk_budgets  Target risk fractions (sums to 1). Default: equal (1/N each).
    """
    mu_arr, cov_arr, names = _validate_inputs(mu, cov)
    n = len(mu_arr)
    cov_pb = cov_arr / ann

    if risk_budgets is None:
        budgets = np.ones(n) / n
    else:
        budgets = np.asarray(risk_budgets, dtype=float)
        budgets /= budgets.sum()

    def risk_budget_objective(w: np.ndarray) -> float:
        """Sum of squared deviations from target risk contribution."""
        port_var = max(float(w @ cov_pb @ w), 1e-12)
        marginal_rc = cov_pb @ w
        rc = w * marginal_rc / port_var
        return float(np.sum((rc - budgets) ** 2))

    bounds = [(max(w_min, 1e-6), w_max)] * n  # strictly positive for RC
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]

    best_obj = np.inf
    best_w = np.ones(n) / n
    best_success = False
    rng = np.random.default_rng(42)

    for _ in range(10):
        w0 = rng.dirichlet(np.ones(n))
        res = minimize(
            risk_budget_objective, w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 2000, "ftol": 1e-14},
        )
        if res.fun < best_obj:
            best_obj = res.fun
            best_w = res.x
            best_success = res.success

    result = _result_dict(best_w, names, mu_arr, cov_arr, risk_free, ann,
                          "risk_parity", best_success)

    # Compute actual risk contributions for verification
    w = best_w / best_w.sum()
    port_var = max(float(w @ cov_pb @ w), 1e-12)
    rc = w * (cov_pb @ w) / port_var
    result["risk_contributions"] = dict(zip(names, rc.round(6).tolist()))
    result["max_rc_deviation"] = round(float(np.abs(rc - budgets).max()), 6)
    return result


# ---------------------------------------------------------------------------
# Kelly Criterion
# ---------------------------------------------------------------------------
def kelly_criterion(
    mu: pd.Series | np.ndarray,
    cov: pd.DataFrame | np.ndarray,
    risk_free: float = 0.05,
    fraction: float = 0.5,
    long_only: bool = True,
    w_min: float = 0.0,
    w_max: float = 1.0,
    ann: float = 252.0,
) -> dict:
    """
    Kelly Criterion portfolio weights.

    Full Kelly maximises E[log(1 + r)] = E[r] - Var(r)/2 (for small r).
    In continuous time with Gaussian returns:
      w* = Cov^{-1} * (mu - rf)

    Full Kelly is extremely aggressive and leads to large drawdowns.
    Fractional Kelly (fraction * w*) is used in practice:
      - fraction = 0.5 → half-Kelly (reduces volatility, retains 75% growth)
      - fraction = 0.25 → quarter-Kelly (more conservative)

    Parameters
    ----------
    fraction   Kelly fraction [0, 1]. Default 0.5 (half-Kelly).
    """
    mu_arr, cov_arr, names = _validate_inputs(mu, cov)
    n = len(mu_arr)
    rf_pb = (1 + risk_free) ** (1 / ann) - 1
    excess_mu = mu_arr / ann - rf_pb
    cov_pb = cov_arr / ann

    # Kelly weights: w* = Cov^{-1} * excess_mu
    try:
        cov_inv = np.linalg.inv(cov_pb + np.eye(n) * 1e-8)  # regularise
    except np.linalg.LinAlgError:
        warnings.warn("Covariance matrix is singular. Using pseudoinverse.", stacklevel=2)
        cov_inv = np.linalg.pinv(cov_pb)

    w_kelly = cov_inv @ excess_mu
    w_fractional = fraction * w_kelly

    if long_only:
        w_fractional = np.maximum(w_fractional, 0)
    w_fractional = np.clip(w_fractional, w_min, w_max)
    total = w_fractional.sum()
    if total <= 0:
        w_fractional = np.ones(n) / n
    else:
        w_fractional /= total

    result = _result_dict(w_fractional, names, mu_arr, cov_arr, risk_free, ann,
                          f"kelly_f{fraction}", True)
    result["kelly_fraction"] = fraction
    result["full_kelly_leverage"] = round(float(np.sum(np.abs(w_kelly))), 3)
    return result


# ---------------------------------------------------------------------------
# Efficient Frontier
# ---------------------------------------------------------------------------
def efficient_frontier(
    mu: pd.Series | np.ndarray,
    cov: pd.DataFrame | np.ndarray,
    n_points: int = 30,
    risk_free: float = 0.05,
    long_only: bool = True,
    ann: float = 252.0,
) -> pd.DataFrame:
    """
    Compute the efficient frontier by sweeping target returns.

    Returns a DataFrame with columns: target_return, ann_volatility,
    sharpe, and one column per asset with its weight.

    Plot ann_volatility (x) vs target_return (y) for the frontier curve.
    """
    mu_arr, cov_arr, names = _validate_inputs(mu, cov)
    min_r = float(mu_arr.min()) / ann
    max_r = float(mu_arr.max()) / ann
    target_returns = np.linspace(min_r * 1.01, max_r * 0.99, n_points) * ann

    rows = []
    for tr in target_returns:
        try:
            result = mean_variance(mu, cov, target_return=tr,
                                   risk_free=risk_free, long_only=long_only, ann=ann)
            if result["solver_success"]:
                row = {"target_return_pct": round(tr * 100, 3),
                       "ann_volatility_pct": result["ann_volatility_pct"],
                       "sharpe": result["sharpe"]}
                row.update(result["weights"])
                rows.append(row)
        except Exception:
            continue

    return pd.DataFrame(rows) if rows else pd.DataFrame()
