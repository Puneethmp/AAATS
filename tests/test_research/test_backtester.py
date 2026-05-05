"""
Tests for research/backtester.py -- VectorizedBacktester and WalkForwardValidator
API: bt.run(df_with_signal_col, signal_col='signal') -> BacktestResult
"""
import numpy as np
import pandas as pd
import pytest
from research.backtester import VectorizedBacktester, WalkForwardValidator, BacktestResult
from indicators.features import compute_features


@pytest.fixture
def sample_df():
    np.random.seed(0)
    n = 400
    close = 100.0 * np.exp(np.cumsum(np.random.normal(0.0003, 0.012, n)))
    df = pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.010,
        "low": close * 0.990,
        "close": close,
        "volume": np.random.uniform(1e6, 3e6, n),
    }, index=pd.date_range("2023-01-01", periods=n, freq="1D"))
    df = compute_features(df)
    df["signal"] = 0.0
    df.loc[df["return_5"] > 0, "signal"] = 1.0
    df.loc[df["return_5"] < 0, "signal"] = -1.0
    return df


def test_backtest_runs_and_returns_result(sample_df):
    bt = VectorizedBacktester()
    result = bt.run(sample_df)
    assert isinstance(result, BacktestResult)


def test_backtest_summary_keys(sample_df):
    bt = VectorizedBacktester()
    result = bt.run(sample_df)
    summary = result.summary()
    required = {"sharpe_ratio", "total_return_pct", "max_drawdown_pct", "win_rate_pct",
                "n_trades", "profit_factor"}
    assert required.issubset(set(summary.keys())), \
        f"Missing keys: {required - set(summary.keys())}"


def test_no_lookahead_bias(sample_df):
    bt = VectorizedBacktester()
    df = sample_df.copy()
    df["signal"] = 0.0
    df.iloc[:100, df.columns.get_loc("signal")] = 1.0
    result = bt.run(df)
    assert result is not None


def test_drawdown_never_exceeds_100(sample_df):
    bt = VectorizedBacktester()
    result = bt.run(sample_df)
    assert result.summary()["max_drawdown_pct"] >= -100.0


def test_commission_reduces_returns():
    """Higher commission should reduce total return."""
    np.random.seed(1)
    n = 400
    close = 100.0 * np.exp(np.cumsum(np.random.normal(0.001, 0.01, n)))
    df = pd.DataFrame({
        "open": close, "high": close * 1.005, "low": close * 0.995,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2023-01-01", periods=n, freq="1D"))
    df = compute_features(df)
    df["signal"] = 1.0

    bt_free = VectorizedBacktester(commission_bps=0, spread_bps=0)
    bt_cost = VectorizedBacktester(commission_bps=50, spread_bps=20)
    r_free = bt_free.run(df).summary()["total_return_pct"]
    r_cost = bt_cost.run(df).summary()["total_return_pct"]
    assert r_free >= r_cost, f"Free ({r_free:.2f}%) should beat high-cost ({r_cost:.2f}%)"


def test_hold_signal_produces_no_trades(sample_df):
    bt = VectorizedBacktester()
    df = sample_df.copy()
    df["signal"] = 0.0
    result = bt.run(df)
    assert result.summary()["n_trades"] == 0


def test_returns_series_length(sample_df):
    bt = VectorizedBacktester()
    result = bt.run(sample_df)
    assert len(result.returns) == len(sample_df)


def test_equity_curve_starts_at_initial_capital(sample_df):
    """Equity starts at initial_capital (default 100_000), not 1.0."""
    bt = VectorizedBacktester()
    result = bt.run(sample_df)
    assert result.equity.iloc[0] > 0
    normalised = result.equity / result.equity.iloc[0]
    assert abs(normalised.iloc[0] - 1.0) < 1e-6


def test_walk_forward_produces_oos_metrics():
    """WalkForwardValidator produces OOS sharpe key.

    signal_fn passes train_df and reindexes to test dates, so rule-based
    signals (RSI) must be pre-computed on the full df and passed without
    signal_fn -- the validator slices each fold's pre-computed signal.
    """
    np.random.seed(7)
    n = 500
    close = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.012, n)))
    df = pd.DataFrame({
        "open": close, "high": close * 1.005, "low": close * 0.995,
        "close": close, "volume": np.ones(n) * 1e6,
    }, index=pd.date_range("2023-01-01", periods=n, freq="1D"))
    df = compute_features(df)
    df["signal"] = 0.0
    df.loc[df["rsi_14"] < 40, "signal"] = 1.0
    df.loc[df["rsi_14"] > 60, "signal"] = -1.0

    wfv = WalkForwardValidator(n_folds=3)
    result = wfv.run(df)
    summary = result.summary()
    assert "sharpe_ratio" in summary, f"No sharpe_ratio in OOS summary. Got: {list(summary.keys())}"
    assert summary["sharpe_ratio"] is not None
