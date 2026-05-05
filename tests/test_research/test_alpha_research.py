"""
Tests for research/alpha_research.py — IC/IR, alpha decay, quantile returns
API verified against actual module output.
"""
import numpy as np
import pandas as pd
import pytest
from research.alpha_research import (
    compute_ic, compute_ir, alpha_decay, quantile_returns, factor_turnover, alpha_summary,
)


@pytest.fixture
def correlated_signals():
    np.random.seed(99)
    n = 500
    true_factor = np.random.normal(0, 1, n)
    signal = pd.Series(true_factor + np.random.normal(0, 0.5, n))
    fwd_ret = pd.Series(true_factor * 0.01 + np.random.normal(0, 0.02, n))
    return signal, fwd_ret


@pytest.fixture
def noise_signals():
    np.random.seed(7)
    n = 500
    return pd.Series(np.random.normal(0, 1, n)), pd.Series(np.random.normal(0, 0.02, n))


# ── IC ───────────────────────────────────────────────────────────────────────
def test_ic_positive_for_correlated_signal(correlated_signals):
    signal, fwd_ret = correlated_signals
    ic = compute_ic(signal, fwd_ret, method="spearman")
    assert ic > 0.05, f"Expected IC > 0.05 for correlated signal, got {ic:.4f}"


def test_ic_near_zero_for_noise(noise_signals):
    signal, fwd_ret = noise_signals
    ic = compute_ic(signal, fwd_ret, method="spearman")
    assert abs(ic) < 0.15, f"Expected IC ≈ 0 for noise, got {ic:.4f}"


def test_ic_in_range(correlated_signals):
    signal, fwd_ret = correlated_signals
    assert -1.0 <= compute_ic(signal, fwd_ret) <= 1.0


# ── IR ───────────────────────────────────────────────────────────────────────
def test_ir_has_required_keys(correlated_signals):
    signal, fwd_ret = correlated_signals
    stats = compute_ir(signal, fwd_ret)
    for key in ("mean_ic", "ic_std", "ir", "t_stat", "p_value", "rolling_ic", "pct_positive_ic"):
        assert key in stats, f"Missing key: {key}"


def test_ir_positive_for_good_signal(correlated_signals):
    signal, fwd_ret = correlated_signals
    stats = compute_ir(signal, fwd_ret)
    assert stats["ir"] > 0


def test_ir_rolling_is_series(correlated_signals):
    signal, fwd_ret = correlated_signals
    stats = compute_ir(signal, fwd_ret)
    assert isinstance(stats["rolling_ic"], pd.Series)


# ── Alpha decay ───────────────────────────────────────────────────────────────
def test_alpha_decay_returns_dataframe(correlated_signals):
    signal, fwd_ret = correlated_signals
    decay = alpha_decay(signal, fwd_ret, max_lag=10)
    assert isinstance(decay, pd.DataFrame)
    assert "ic" in decay.columns
    assert "t_stat" in decay.columns
    assert len(decay) == 10


def test_alpha_decay_ic_at_lag1_positive(correlated_signals):
    signal, fwd_ret = correlated_signals
    decay = alpha_decay(signal, fwd_ret, max_lag=10)
    assert decay["ic"].iloc[0] > 0


# ── Quantile returns ──────────────────────────────────────────────────────────
def test_quantile_returns_shape(correlated_signals):
    signal, fwd_ret = correlated_signals
    qt = quantile_returns(signal, fwd_ret, n_quantiles=5)
    assert isinstance(qt, pd.DataFrame)
    assert len(qt) == 5
    assert "mean_return" in qt.columns


def test_quantile_top_beats_bottom(correlated_signals):
    signal, fwd_ret = correlated_signals
    qt = quantile_returns(signal, fwd_ret, n_quantiles=5)
    assert qt["mean_return"].iloc[-1] > qt["mean_return"].iloc[0]


# ── Factor turnover ───────────────────────────────────────────────────────────
def test_factor_turnover_returns_dataframe(correlated_signals):
    signal, _ = correlated_signals
    to = factor_turnover(signal, lags=5)
    assert isinstance(to, pd.DataFrame)
    assert "autocorrelation" in to.columns
    assert len(to) == 5


# ── Alpha summary ─────────────────────────────────────────────────────────────
def test_alpha_summary_has_verdict(correlated_signals):
    signal, fwd_ret = correlated_signals
    result = alpha_summary(signal, fwd_ret, forward_horizon=1)
    assert "verdict" in result


def test_alpha_summary_has_ic_stats(correlated_signals):
    signal, fwd_ret = correlated_signals
    result = alpha_summary(signal, fwd_ret, forward_horizon=1)
    assert "ic_stats" in result


def test_alpha_summary_has_quantile_analysis(correlated_signals):
    signal, fwd_ret = correlated_signals
    result = alpha_summary(signal, fwd_ret, forward_horizon=1)
    assert "quantile_analysis" in result


def test_alpha_summary_verdict_is_dict(correlated_signals):
    signal, fwd_ret = correlated_signals
    result = alpha_summary(signal, fwd_ret, forward_horizon=1)
    assert isinstance(result["verdict"], dict)


def test_alpha_summary_ic_within_ic_stats(correlated_signals):
    signal, fwd_ret = correlated_signals
    result = alpha_summary(signal, fwd_ret, forward_horizon=1)
    ic_stats = result["ic_stats"]
    assert "mean_ic" in ic_stats or "ic" in ic_stats
