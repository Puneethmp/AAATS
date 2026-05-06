"""
Post-hoc validators for AAATS backtesting results.

Enforces Blueprint Section 8 Rules 1, 4, 5:
  Rule 1: Timestamp gate  — no lookahead bias in signal generation
  Rule 4: Walk-forward gate — train/test split has zero data leakage
  Rule 5: (implied) Overfitting thresholds — Sharpe>3.0, PF>3.0, WR>80%
"""

from __future__ import annotations

import math

import pandas as pd

from backtesting.engine import BacktestResult
from foundation.logger import get_logger

# ── Overfitting thresholds (named constants — not magic numbers) ──────────────
OVERFITTING_SHARPE_THRESHOLD: float = 3.0
OVERFITTING_PF_THRESHOLD: float = 3.0
OVERFITTING_WIN_RATE_THRESHOLD: float = 0.80

log = get_logger(market="us", module="backtesting_validators")


def check_lookahead_bias(
    features_df: pd.DataFrame,
    signal_timestamps: list,
) -> list[dict]:
    """Detect lookahead bias in a completed backtest.

    For each signal_timestamp T, checks that the features dataset contains at
    least one row at or before T. If the earliest features row is AFTER T, the
    signal was generated from data that did not yet exist at signal time — a
    lookahead violation.

    Args:
        features_df: Full features DataFrame used in the backtest. Must have a
            'timestamp' column.
        signal_timestamps: List of timestamps at which signals were generated.

    Returns:
        List of violation dicts: [{"timestamp": pd.Timestamp, "reason": str}]
        Empty list means no violations detected.
    """
    violations: list[dict] = []

    if features_df.empty or not signal_timestamps:
        log.debug("check_lookahead_bias: empty input — nothing to check")
        return violations

    if "timestamp" not in features_df.columns:
        log.error(
            "check_lookahead_bias: features_df missing required 'timestamp' column"
        )
        return violations

    ts_col = pd.to_datetime(features_df["timestamp"])

    for sig_ts in signal_timestamps:
        sig_ts_pd = pd.Timestamp(sig_ts)
        available = ts_col[ts_col <= sig_ts_pd]

        if available.empty:
            min_features_ts = ts_col.min()
            reason = (
                f"No features row at or before signal time {sig_ts_pd} — "
                f"features dataset starts at {min_features_ts}; "
                f"signal was generated from future data"
            )
            log.warning(
                "Lookahead bias violation",
                signal_timestamp=str(sig_ts_pd),
                features_min_timestamp=str(min_features_ts),
            )
            violations.append({"timestamp": sig_ts_pd, "reason": reason})

    return violations


def check_overfitting(result: BacktestResult) -> tuple[bool, str | None]:
    """Check a BacktestResult for statistical overfitting markers.

    Evaluates three independent thresholds; any breach marks the result as
    overfitted:
      - Sharpe ratio > 3.0
      - Profit factor > 3.0 (including inf — engine returns inf when no losing
        trades exist; see FLAGGED_ISSUES.md 2026-04-27 engine INTERFACE note)
      - Win rate > 80%

    Args:
        result: Completed BacktestResult from run_backtest().

    Returns:
        (is_overfitted, reason). reason is None when no overfitting detected.
    """
    reasons: list[str] = []

    if result.sharpe_ratio > OVERFITTING_SHARPE_THRESHOLD:
        reasons.append(
            f"Sharpe {result.sharpe_ratio:.4f} exceeds threshold {OVERFITTING_SHARPE_THRESHOLD}"
        )

    pf = result.profit_factor
    if math.isinf(pf) or pf > OVERFITTING_PF_THRESHOLD:
        reasons.append(
            f"Profit factor {pf} exceeds threshold {OVERFITTING_PF_THRESHOLD}"
        )

    if result.win_rate > OVERFITTING_WIN_RATE_THRESHOLD:
        reasons.append(
            f"Win rate {result.win_rate:.2%} exceeds threshold "
            f"{OVERFITTING_WIN_RATE_THRESHOLD:.0%}"
        )

    if reasons:
        combined = "; ".join(reasons)
        log.warning("Overfitting markers detected", reasons=combined)
        return True, combined

    return False, None


def validate_walk_forward_split(
    train_end: pd.Timestamp,
    test_start: pd.Timestamp,
) -> bool:
    """Validate the walk-forward train/test split for data leakage.

    test_start must be strictly greater than train_end. Equal timestamps are
    invalid — the same bar would appear in both windows, leaking training
    labels into the test set.

    Args:
        train_end: Last timestamp of the training window (inclusive).
        test_start: First timestamp of the out-of-sample test window.

    Returns:
        True if test_start > train_end (clean split).
        False if test_start <= train_end (data leakage — hard rejection).
    """
    result = pd.Timestamp(test_start) > pd.Timestamp(train_end)
    if not result:
        log.warning(
            "Walk-forward split violation — data leakage detected",
            train_end=str(train_end),
            test_start=str(test_start),
        )
    return result
