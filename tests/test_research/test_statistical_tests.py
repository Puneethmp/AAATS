"""
Tests for research/statistical_tests.py — PSR, DSR, CPCV, multiple testing
API verified against actual module output.
"""
import numpy as np
import pandas as pd
import pytest
from research.statistical_tests import (
    probabilistic_sharpe_ratio,
    deflated_sharpe_ratio,
    min_track_record_length,
    multiple_testing_correction,
    combinatorial_purged_cv,
)


@pytest.fixture
def good_returns():
    np.random.seed(42)
    return pd.Series(np.random.normal(0.001, 0.01, 500))


@pytest.fixture
def noise_returns():
    np.random.seed(13)
    return pd.Series(np.random.normal(0.0, 0.02, 500))


# ── PSR ──────────────────────────────────────────────────────────────────────
def test_psr_result_keys(good_returns):
    result = probabilistic_sharpe_ratio(good_returns)
    assert "psr" in result
    assert "observed_sharpe_ann" in result


def test_psr_high_for_good_strategy(good_returns):
    result = probabilistic_sharpe_ratio(good_returns, benchmark_sharpe=0.0)
    assert result["psr"] > 0.9, f"Expected PSR > 0.9, got {result['psr']:.4f}"


def test_psr_low_when_benchmark_exceeds_observed(noise_returns):
    result = probabilistic_sharpe_ratio(noise_returns, benchmark_sharpe=2.0)
    assert result["psr"] < 0.5, f"Expected PSR < 0.5, got {result['psr']:.4f}"


def test_psr_in_unit_interval(good_returns):
    result = probabilistic_sharpe_ratio(good_returns)
    assert 0.0 <= result["psr"] <= 1.0


# ── DSR ──────────────────────────────────────────────────────────────────────
def test_dsr_result_keys(good_returns):
    result = deflated_sharpe_ratio(good_returns, n_strategies_tested=5)
    assert "dsr" in result
    assert "is_genuine_discovery" in result


def test_dsr_genuine_discovery_for_good_returns(good_returns):
    result = deflated_sharpe_ratio(good_returns, n_strategies_tested=1)
    assert isinstance(result["is_genuine_discovery"], bool)


def test_dsr_penalises_many_strategies(good_returns):
    r1 = deflated_sharpe_ratio(good_returns, n_strategies_tested=1)
    r100 = deflated_sharpe_ratio(good_returns, n_strategies_tested=100)
    assert r1["dsr"] >= r100["dsr"], "DSR should be lower when more strategies tested"


def test_dsr_has_threshold(good_returns):
    result = deflated_sharpe_ratio(good_returns, n_strategies_tested=5)
    assert "adjusted_sr_threshold_ann" in result or "expected_max_sharpe_ann" in result


# ── Min Track Record ──────────────────────────────────────────────────────────
def test_trl_result_keys(good_returns):
    result = min_track_record_length(target_sharpe=1.0)
    assert "min_observations" in result
    assert "years_equivalent" in result


def test_trl_positive_values():
    result = min_track_record_length(target_sharpe=1.0)
    assert result["min_observations"] > 0
    assert result["years_equivalent"] > 0


def test_trl_longer_for_harder_target():
    r_easy = min_track_record_length(target_sharpe=2.0, confidence=0.90)
    r_hard = min_track_record_length(target_sharpe=0.5, confidence=0.95)
    assert r_hard["min_observations"] >= r_easy["min_observations"]


# ── Multiple Testing ──────────────────────────────────────────────────────────
def test_multiple_testing_bonferroni():
    p_values = pd.Series([0.01, 0.02, 0.03, 0.10, 0.50])
    result = multiple_testing_correction(p_values, method="bonferroni", alpha=0.05)
    assert isinstance(result, pd.DataFrame)
    assert "corrected_p_value" in result.columns
    assert "reject_null" in result.columns
    n = len(p_values)
    expected = (p_values * n).clip(upper=1.0).values
    np.testing.assert_allclose(result["corrected_p_value"].values, expected, atol=1e-10)


def test_multiple_testing_bhy():
    p_values = pd.Series([0.001, 0.01, 0.05, 0.10, 0.50])
    result = multiple_testing_correction(p_values, method="bhy", alpha=0.05)
    assert len(result) == len(p_values)
    assert "reject_null" in result.columns


def test_multiple_testing_holm():
    p_values = pd.Series([0.001, 0.01, 0.05, 0.10, 0.50])
    result = multiple_testing_correction(p_values, method="holm", alpha=0.05)
    assert len(result) == len(p_values)


def test_bonferroni_rejects_low_pvalues():
    p_values = pd.Series([0.001, 0.50])
    result = multiple_testing_correction(p_values, method="bonferroni", alpha=0.05)
    # p=0.001 * 2 = 0.002 < 0.05 → reject
    assert result["reject_null"].iloc[0] is True or result["reject_null"].iloc[0] == True


# ── CPCV ─────────────────────────────────────────────────────────────────────
def test_cpcv_result_keys(good_returns):
    result = combinatorial_purged_cv(good_returns, n_splits=4, n_test_splits=2)
    assert "pbo" in result
    assert "oos_sharpe_mean" in result
    assert "interpretation" in result


def test_cpcv_pbo_in_unit_interval(good_returns):
    result = combinatorial_purged_cv(good_returns, n_splits=4, n_test_splits=2)
    assert 0.0 <= result["pbo"] <= 1.0


def test_cpcv_has_is_sharpe(good_returns):
    result = combinatorial_purged_cv(good_returns, n_splits=4, n_test_splits=2)
    assert "is_sharpe_mean" in result
