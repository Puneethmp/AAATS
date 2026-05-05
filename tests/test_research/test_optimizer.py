"""
Tests for portfolio/optimizer.py -- MVO, risk-parity, max-Sharpe, Kelly
"""
import numpy as np
import pandas as pd
import pytest
from portfolio.optimizer import (
    portfolio_stats, mean_variance, max_sharpe, min_variance,
    risk_parity, kelly_criterion, efficient_frontier,
)


@pytest.fixture
def assets():
    """3-asset universe with known properties."""
    np.random.seed(1)
    mu = np.array([0.10, 0.15, 0.08])
    cov = np.array([
        [0.04, 0.01, 0.005],
        [0.01, 0.09, 0.002],
        [0.005, 0.002, 0.0025],
    ])
    return mu, cov


def _w(result):
    """Extract weights as numpy array from optimizer result dict."""
    w = result["weights"]
    if isinstance(w, dict):
        return np.array(list(w.values()))
    return np.asarray(w)


def test_portfolio_stats_sharpe(assets):
    mu, cov = assets
    w = np.array([1/3, 1/3, 1/3])
    stats = portfolio_stats(w, mu, cov, risk_free=0.05)
    assert "sharpe" in stats
    assert stats["sharpe"] > 0


def test_weights_sum_to_one_mean_variance(assets):
    mu, cov = assets
    result = mean_variance(mu, cov, target_return=0.10)
    w = _w(result)
    assert abs(w.sum() - 1.0) < 1e-4


def test_mean_variance_long_only(assets):
    mu, cov = assets
    result = mean_variance(mu, cov, target_return=0.10)
    w = _w(result)
    assert (w >= -1e-6).all(), "All weights should be non-negative (long-only)"


def test_max_sharpe_weights_sum_to_one(assets):
    mu, cov = assets
    result = max_sharpe(mu, cov)
    w = _w(result)
    assert abs(w.sum() - 1.0) < 1e-4


def test_min_variance_weights_sum_to_one(assets):
    mu, cov = assets
    result = min_variance(mu, cov)
    w = _w(result)
    assert abs(w.sum() - 1.0) < 1e-4


def test_min_variance_lower_vol_than_equal_weight(assets):
    mu, cov = assets
    result = min_variance(mu, cov)
    w_mv = _w(result)
    w_eq = np.ones(3) / 3
    vol_mv = float(np.sqrt(w_mv @ cov @ w_mv))
    vol_eq = float(np.sqrt(w_eq @ cov @ w_eq))
    assert vol_mv <= vol_eq + 1e-6


def test_risk_parity_runs(assets):
    mu, cov = assets
    result = risk_parity(mu, cov)
    w = _w(result)
    assert abs(w.sum() - 1.0) < 1e-3


def test_risk_parity_approx_equal_risk(assets):
    mu, cov = assets
    result = risk_parity(mu, cov)
    w = _w(result)
    marginal = cov @ w
    risk_contrib = w * marginal
    rc = risk_contrib / risk_contrib.sum()
    target = 1.0 / len(w)
    assert (np.abs(rc - target) < 0.15).all(), f"Risk contributions not balanced: {rc}"


def test_kelly_criterion_runs(assets):
    mu, cov = assets
    result = kelly_criterion(mu, cov)
    w = _w(result)
    assert len(w) == 3


def test_efficient_frontier_returns_dataframe(assets):
    mu, cov = assets
    ef = efficient_frontier(mu, cov, n_points=10)
    assert isinstance(ef, pd.DataFrame)
    assert len(ef) == 10
    return_cols = {"target_return_pct", "ann_return", "ann_return_pct"}
    assert bool(return_cols & set(ef.columns)), f"No return col. Got: {list(ef.columns)}"


def test_max_weight_constraint(assets):
    mu, cov = assets
    result = max_sharpe(mu, cov, w_max=0.50)
    w = _w(result)
    assert (w <= 0.50 + 1e-4).all(), "No weight should exceed max constraint"


def test_portfolio_stats_has_required_keys(assets):
    mu, cov = assets
    w = np.array([0.5, 0.3, 0.2])
    stats = portfolio_stats(w, mu, cov)
    assert "sharpe" in stats
    assert "ann_return" in stats or "ann_return_pct" in stats
    assert "ann_volatility" in stats or "ann_volatility_pct" in stats
