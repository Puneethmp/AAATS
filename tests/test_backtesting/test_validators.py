"""
Tests for backtesting/validators.py.

Covers: lookahead bias detection, overfitting checks (Sharpe, PF, win_rate,
inf PF), walk-forward split validation (valid, invalid, equal).

All tests use synthetic data — no external API calls, no DB access.
"""

import pandas as pd

from backtesting.engine import BacktestResult
from backtesting.validators import (
    check_lookahead_bias,
    check_overfitting,
    validate_walk_forward_split,
)

# ── Shared helpers ────────────────────────────────────────────────────────────


def _make_features(n: int = 5, start: str = "2024-01-01") -> pd.DataFrame:
    """Minimal features DataFrame with a 'timestamp' column."""
    return pd.DataFrame({"timestamp": pd.date_range(start, periods=n, freq="D")})


def _make_result(
    sharpe: float = 1.2,
    profit_factor: float = 1.5,
    win_rate: float = 0.55,
) -> BacktestResult:
    """Factory for a BacktestResult with controllable key metrics."""
    return BacktestResult(
        total_return_pct=0.10,
        sharpe_ratio=sharpe,
        max_drawdown_pct=-0.05,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_trades=10,
        winning_trades=6,
        losing_trades=4,
        avg_win_pct=0.03,
        avg_loss_pct=-0.02,
        equity_curve=[100_000.0, 110_000.0],
        trade_log=[],
        approved=True,
        rejection_reason=None,
    )


# ── Tests: check_lookahead_bias ───────────────────────────────────────────────


def test_no_lookahead():
    """Signal timestamps within features range → empty violations list.

    Uses the first, middle, and last timestamp of the features DataFrame.
    All have features rows at or before them — no lookahead.
    """
    features_df = _make_features(5, "2024-01-01")
    timestamps = features_df["timestamp"].tolist()
    signal_ts = [timestamps[0], timestamps[2], timestamps[4]]

    violations = check_lookahead_bias(features_df, signal_ts)

    assert violations == [], f"Expected no violations, got: {violations}"


def test_lookahead_detected():
    """Signal at T1 but features only start at T3 → violation logged.

    'Future timestamp in features' scenario: the features dataset starts
    AFTER the signal time, meaning the signal was generated from data
    that was not yet available at signal time.
    """
    features_df = _make_features(3, "2024-01-03")
    signal_ts = [pd.Timestamp("2024-01-01")]

    violations = check_lookahead_bias(features_df, signal_ts)

    assert len(violations) == 1, f"Expected 1 violation, got {len(violations)}"
    v = violations[0]
    assert v["timestamp"] == pd.Timestamp("2024-01-01")
    assert "future data" in v["reason"] or "features dataset starts" in v["reason"]


def test_lookahead_empty_features():
    """Empty features_df → empty violations (nothing to check)."""
    empty_df = pd.DataFrame(columns=["timestamp"])
    violations = check_lookahead_bias(empty_df, [pd.Timestamp("2024-01-01")])
    assert violations == []


def test_lookahead_empty_signals():
    """Empty signal_timestamps → empty violations."""
    features_df = _make_features(5)
    violations = check_lookahead_bias(features_df, [])
    assert violations == []


def test_lookahead_multiple_signals_mixed():
    """Only the signals before features window trigger violations.

    Signal at Jan 5 is clean; signal at Jan 1 (before features start at Jan 3)
    is a violation.
    """
    features_df = _make_features(3, "2024-01-03")
    signal_ts = [
        pd.Timestamp("2024-01-01"),  # before features start → violation
        pd.Timestamp("2024-01-05"),  # within features range → clean
    ]

    violations = check_lookahead_bias(features_df, signal_ts)

    assert len(violations) == 1
    assert violations[0]["timestamp"] == pd.Timestamp("2024-01-01")


# ── Tests: check_overfitting ──────────────────────────────────────────────────


def test_overfitting_sharpe():
    """Sharpe = 3.5 → is_overfitted=True, reason mentions Sharpe."""
    result = _make_result(sharpe=3.5, profit_factor=1.5, win_rate=0.55)
    is_overfitted, reason = check_overfitting(result)

    assert is_overfitted is True
    assert reason is not None
    assert "Sharpe" in reason


def test_overfitting_winrate():
    """win_rate = 0.85 → is_overfitted=True, reason mentions win rate."""
    result = _make_result(sharpe=1.2, profit_factor=1.5, win_rate=0.85)
    is_overfitted, reason = check_overfitting(result)

    assert is_overfitted is True
    assert reason is not None
    assert "Win rate" in reason


def test_overfitting_profit_factor():
    """Profit factor = 3.5 → is_overfitted=True, reason mentions Profit factor."""
    result = _make_result(sharpe=1.2, profit_factor=3.5, win_rate=0.55)
    is_overfitted, reason = check_overfitting(result)

    assert is_overfitted is True
    assert reason is not None
    assert "Profit factor" in reason


def test_overfitting_inf_profit_factor():
    """Profit factor = inf (all winning trades) → is_overfitted=True.

    Guards against the engine.py known issue where profit_factor returns
    float('inf') when no losing trades exist (FLAGGED_ISSUES.md 2026-04-27).
    """
    result = _make_result(sharpe=1.2, profit_factor=float("inf"), win_rate=0.55)
    is_overfitted, reason = check_overfitting(result)

    assert is_overfitted is True
    assert reason is not None
    assert "Profit factor" in reason


def test_no_overfitting():
    """All metrics below thresholds → is_overfitted=False, reason=None."""
    result = _make_result(sharpe=1.5, profit_factor=1.8, win_rate=0.60)
    is_overfitted, reason = check_overfitting(result)

    assert is_overfitted is False
    assert reason is None


def test_overfitting_boundary_sharpe():
    """Sharpe = exactly 3.0 → NOT overfitted (threshold is strictly >3.0)."""
    result = _make_result(sharpe=3.0, profit_factor=1.5, win_rate=0.55)
    is_overfitted, reason = check_overfitting(result)

    assert is_overfitted is False
    assert reason is None


# ── Tests: validate_walk_forward_split ───────────────────────────────────────


def test_walk_forward_valid():
    """test_start > train_end → True (valid split, no leakage)."""
    train_end = pd.Timestamp("2023-12-31")
    test_start = pd.Timestamp("2024-01-01")

    assert validate_walk_forward_split(train_end, test_start) is True


def test_walk_forward_invalid():
    """test_start < train_end → False (test window overlaps training data)."""
    train_end = pd.Timestamp("2024-01-05")
    test_start = pd.Timestamp("2024-01-03")

    assert validate_walk_forward_split(train_end, test_start) is False


def test_walk_forward_equal():
    """test_start == train_end → False (same bar in both windows = leakage)."""
    ts = pd.Timestamp("2024-06-15")

    assert validate_walk_forward_split(ts, ts) is False
