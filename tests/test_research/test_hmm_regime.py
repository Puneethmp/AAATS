"""
Tests for intelligence/regime/hmm_regime.py — Gaussian HMM Regime Detection
"""
import numpy as np
import pandas as pd
import pytest
from intelligence.regime.hmm_regime import GaussianHMM


@pytest.fixture
def market_df():
    """Synthetic market data with 2 regimes."""
    np.random.seed(42)
    n = 400
    # Regime 1 (bull): positive drift, low vol
    r1 = np.random.normal(0.001, 0.008, 200)
    # Regime 2 (bear): negative drift, high vol
    r2 = np.random.normal(-0.002, 0.020, 200)
    returns = np.concatenate([r1, r2])
    close = 100.0 * np.exp(np.cumsum(returns))
    df = pd.DataFrame({
        "close": close,
        "volume": np.random.uniform(1e6, 5e6, n),
    }, index=pd.date_range("2023-01-01", periods=n, freq="1D"))
    return df


def test_hmm_fits_without_error(market_df):
    hmm = GaussianHMM(n_states=2, n_iter=30)
    hmm.fit(market_df)
    assert hmm._fitted is True


def test_hmm_predict_returns_series(market_df):
    hmm = GaussianHMM(n_states=2, n_iter=30)
    hmm.fit(market_df)
    states = hmm.predict(market_df)
    assert isinstance(states, pd.Series)
    assert len(states) == len(market_df)


def test_hmm_labels_are_bull_bear(market_df):
    hmm = GaussianHMM(n_states=2, n_iter=30)
    hmm.fit(market_df)
    states = hmm.predict(market_df)
    assert set(states.unique()).issubset({"bull", "bear"}), \
        f"Unexpected labels: {states.unique()}"


def test_hmm_predict_proba_shape(market_df):
    hmm = GaussianHMM(n_states=2, n_iter=30)
    hmm.fit(market_df)
    proba = hmm.predict_proba(market_df)
    assert proba.shape == (len(market_df), 2)


def test_hmm_probabilities_sum_to_one(market_df):
    hmm = GaussianHMM(n_states=2, n_iter=30)
    hmm.fit(market_df)
    proba = hmm.predict_proba(market_df)
    row_sums = proba.sum(axis=1)
    assert (abs(row_sums - 1.0) < 1e-6).all(), "Probabilities must sum to 1"


def test_hmm_3_states(market_df):
    hmm = GaussianHMM(n_states=3, n_iter=30)
    hmm.fit(market_df)
    states = hmm.predict(market_df)
    assert set(states.unique()).issubset({"bull", "bear", "sideways"})


def test_hmm_invalid_n_states():
    with pytest.raises(ValueError, match="n_states must be 2 or 3"):
        GaussianHMM(n_states=4)


def test_hmm_predict_without_fit_raises(market_df):
    hmm = GaussianHMM(n_states=2)
    with pytest.raises(RuntimeError, match="Call fit()"):
        hmm.predict(market_df)


def test_hmm_regime_report_structure(market_df):
    hmm = GaussianHMM(n_states=2, n_iter=30)
    hmm.fit(market_df)
    report = hmm.regime_report(market_df)
    assert "regime_stats" in report
    assert "transition_matrix" in report
    assert "log_likelihood" in report


def test_hmm_regime_report_stats_keys(market_df):
    hmm = GaussianHMM(n_states=2, n_iter=30)
    hmm.fit(market_df)
    report = hmm.regime_report(market_df)
    for label, stats in report["regime_stats"].items():
        expected_keys = {"frequency_pct", "mean_return_pct", "ann_volatility_pct",
                         "mean_duration_bars", "n_episodes"}
        assert expected_keys.issubset(set(stats.keys()))


def test_hmm_bull_regime_higher_return_than_bear(market_df):
    """Bull regime should have higher mean return than bear regime."""
    hmm = GaussianHMM(n_states=2, n_iter=50, random_state=42)
    hmm.fit(market_df)
    report = hmm.regime_report(market_df)
    stats = report["regime_stats"]
    if "bull" in stats and "bear" in stats:
        assert stats["bull"]["mean_return_pct"] > stats["bear"]["mean_return_pct"], \
            "Bull regime should have higher mean return than bear"


def test_hmm_deterministic(market_df):
    """Same random_state should produce same results."""
    hmm1 = GaussianHMM(n_states=2, n_iter=30, random_state=7)
    hmm2 = GaussianHMM(n_states=2, n_iter=30, random_state=7)
    hmm1.fit(market_df)
    hmm2.fit(market_df)
    states1 = hmm1.predict(market_df)
    states2 = hmm2.predict(market_df)
    assert (states1 == states2).all(), "Same seed should give identical results"
