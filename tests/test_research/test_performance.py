"""
Tests for research/performance.py
Actual API keys verified from module inspection.
"""
import numpy as np
import pandas as pd
import pytest
from research.performance import (
    compute_metrics, brinson_attribution, rolling_metrics,
    drawdown_analysis, performance_report,
)


@pytest.fixture
def good_returns():
    np.random.seed(42)
    return pd.Series(np.random.normal(0.001, 0.01, 500))


@pytest.fixture
def benchmark_returns():
    np.random.seed(99)
    return pd.Series(np.random.normal(0.0005, 0.012, 500))


def test_compute_metrics_has_sharpe(good_returns):
    m = compute_metrics(good_returns)
    assert "sharpe_ratio" in m


def test_compute_metrics_has_drawdown(good_returns):
    m = compute_metrics(good_returns)
    assert "max_drawdown_pct" in m


def test_compute_metrics_has_total_return(good_returns):
    m = compute_metrics(good_returns)
    assert "total_return_pct" in m


def test_sharpe_positive_for_good_returns(good_returns):
    m = compute_metrics(good_returns)
    assert m["sharpe_ratio"] > 0


def test_max_drawdown_non_positive(good_returns):
    m = compute_metrics(good_returns)
    assert m["max_drawdown_pct"] <= 0


def test_win_rate_in_range(good_returns):
    m = compute_metrics(good_returns)
    key = "win_rate_pct" if "win_rate_pct" in m else "win_rate"
    assert 0.0 <= m[key] <= 100.0


def test_rolling_metrics_returns_dataframe(good_returns):
    rm = rolling_metrics(good_returns, window=60)
    assert isinstance(rm, pd.DataFrame)
    assert len(rm) == len(good_returns)


def test_rolling_metrics_has_sharpe_column(good_returns):
    rm = rolling_metrics(good_returns, window=60)
    sharpe_cols = [c for c in rm.columns if "sharpe" in c.lower()]
    assert len(sharpe_cols) > 0, f"No sharpe column. Got: {list(rm.columns)}"


def test_drawdown_analysis_returns_dataframe(good_returns):
    d = drawdown_analysis(good_returns)
    assert isinstance(d, pd.DataFrame)


def test_drawdown_has_depth_col(good_returns):
    d = drawdown_analysis(good_returns)
    assert "depth_pct" in d.columns


def test_drawdown_has_duration_col(good_returns):
    d = drawdown_analysis(good_returns)
    assert "duration_bars" in d.columns


def test_brinson_attribution_needs_series():
    """Brinson expects pd.Series inputs."""
    port_w = pd.Series({"A": 0.6, "B": 0.4})
    bench_w = pd.Series({"A": 0.5, "B": 0.5})
    port_r = pd.Series({"A": 0.10, "B": 0.05})
    bench_r = pd.Series({"A": 0.08, "B": 0.04})
    result = brinson_attribution(port_w, bench_w, port_r, bench_r)
    assert isinstance(result, (dict, pd.DataFrame))


def test_brinson_has_allocation_effect():
    port_w = pd.Series({"A": 0.6, "B": 0.4})
    bench_w = pd.Series({"A": 0.5, "B": 0.5})
    port_r = pd.Series({"A": 0.10, "B": 0.05})
    bench_r = pd.Series({"A": 0.08, "B": 0.04})
    result = brinson_attribution(port_w, bench_w, port_r, bench_r)
    if isinstance(result, dict):
        has_alloc = any("alloc" in k.lower() or "total_active" in k.lower()
                        for k in result.keys())
    else:
        has_alloc = any("alloc" in c.lower() for c in result.columns)
    assert has_alloc, f"Brinson should have allocation column. Got: {list(result.keys() if isinstance(result,dict) else result.columns)}"


def test_performance_report_is_dict(good_returns, benchmark_returns):
    report = performance_report(good_returns, benchmark_returns)
    assert isinstance(report, dict)
    assert len(report) > 0
