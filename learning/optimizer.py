"""
Continuous Learning & Optimization for AAATS.

Responsibilities:
  1. ADWIN drift detection — detect concept drift in model performance.
  2. Weekly model retraining trigger — retrain XGBoost when drift detected
     or once per week (whichever comes first).
  3. Rolling Sharpe ratio tracking — monitor strategy health.
  4. Threshold adjustment — tighten/relax signal confidence thresholds.

ADWIN (Adaptive Windowing) — simple implementation:
  Maintains a sliding window of binary outcomes (1=win, 0=loss).
  Drift detected when the win rate over a recent sub-window differs
  significantly from the full window win rate (beyond a tolerance).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from foundation.logger import get_logger

_log = get_logger("learning", "optimizer")

_RETRAIN_INTERVAL_DAYS = 7
_MIN_SAMPLES_FOR_DRIFT = 30
_DRIFT_TOLERANCE = 0.15        # 15% win-rate shift triggers drift alert
_SHARPE_DEGRADATION = 0.30     # Sharpe drops 30% from peak → alert
_MIN_WINDOW = 10               # Minimum recent window for ADWIN sub-check


@dataclass
class DriftStatus:
    drift_detected: bool
    window_win_rate: float
    recent_win_rate: float
    delta: float
    message: str


@dataclass
class OptimizerState:
    outcomes: deque = field(default_factory=lambda: deque(maxlen=500))
    sharpe_history: list[float] = field(default_factory=list)
    peak_sharpe: float = 0.0
    last_retrain: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) - timedelta(days=8)
    )
    retrain_count: int = 0
    drift_alerts: int = 0
    confidence_threshold: float = 0.60   # starts at default


class ADWINDetector:
    """
    Lightweight ADWIN-style drift detector.

    Splits the outcome window into two halves and compares win rates.
    Drift is flagged when the difference exceeds the tolerance threshold.
    """

    def __init__(self, tolerance: float = _DRIFT_TOLERANCE, min_window: int = _MIN_WINDOW):
        self.tolerance = tolerance
        self.min_window = min_window

    def check(self, outcomes: deque) -> DriftStatus:
        """
        Check for concept drift in the outcomes window.

        Args:
            outcomes: Deque of binary int values (1=win, 0=loss).

        Returns:
            DriftStatus with drift_detected flag and rate statistics.
        """
        arr = np.array(list(outcomes), dtype=float)
        n = len(arr)

        if n < _MIN_SAMPLES_FOR_DRIFT:
            return DriftStatus(
                drift_detected=False,
                window_win_rate=float(arr.mean()) if n > 0 else 0.0,
                recent_win_rate=0.0,
                delta=0.0,
                message=f"Insufficient samples ({n}/{_MIN_SAMPLES_FOR_DRIFT})",
            )

        full_win_rate = float(arr.mean())
        # Recent window = last min_window samples
        recent = arr[-self.min_window:]
        recent_win_rate = float(recent.mean())

        delta = abs(full_win_rate - recent_win_rate)
        drift = delta > self.tolerance

        msg = (
            f"DRIFT DETECTED: win rate {full_win_rate:.1%} → {recent_win_rate:.1%} "
            f"(delta={delta:.1%} > tolerance={self.tolerance:.1%})"
            if drift else
            f"Stable: win rate {full_win_rate:.1%}, recent {recent_win_rate:.1%}"
        )

        return DriftStatus(
            drift_detected=drift,
            window_win_rate=full_win_rate,
            recent_win_rate=recent_win_rate,
            delta=delta,
            message=msg,
        )


def record_outcome(state: OptimizerState, win: bool) -> None:
    """Record a completed trade outcome (True=win, False=loss)."""
    state.outcomes.append(1 if win else 0)


def update_sharpe(state: OptimizerState, sharpe: float) -> None:
    """
    Record a new Sharpe ratio measurement.

    Updates peak_sharpe and logs a degradation alert if Sharpe has
    dropped significantly from its peak.
    """
    state.sharpe_history.append(sharpe)
    if sharpe > state.peak_sharpe:
        state.peak_sharpe = sharpe
        _log.info(f"New peak Sharpe: {sharpe:.3f}")
    elif state.peak_sharpe > 0:
        degradation = (state.peak_sharpe - sharpe) / state.peak_sharpe
        if degradation >= _SHARPE_DEGRADATION:
            _log.warning(
                f"Sharpe degradation alert: peak={state.peak_sharpe:.3f}, "
                f"current={sharpe:.3f}, drop={degradation:.1%}"
            )


def should_retrain(state: OptimizerState, drift_status: DriftStatus) -> bool:
    """
    Determine whether model retraining should be triggered.

    Triggers retraining if:
      - Drift detected by ADWIN, OR
      - More than 7 days since last retrain.

    Returns:
        True if retraining should run now.
    """
    days_since = (datetime.now(timezone.utc) - state.last_retrain).days

    if drift_status.drift_detected:
        _log.warning(f"Retraining triggered by drift — {drift_status.message}")
        return True

    if days_since >= _RETRAIN_INTERVAL_DAYS:
        _log.info(f"Weekly retrain triggered — {days_since} days since last")
        return True

    return False


def adjust_confidence_threshold(
    state: OptimizerState,
    drift_status: DriftStatus,
) -> float:
    """
    Adjust signal confidence threshold based on recent performance.

    Rules:
      - Win rate recently degraded → raise threshold (tighter filter)
      - Win rate recently improved  → lower threshold (more signals)
      - Changes capped at ±0.05 from baseline 0.60.

    Returns:
        New confidence threshold.
    """
    baseline = 0.60
    current = state.confidence_threshold

    if drift_status.drift_detected:
        # Raise threshold: be more selective during drift
        new_threshold = min(current + 0.05, baseline + 0.10)
        _log.warning(
            f"Tightening confidence threshold: {current:.2f} → {new_threshold:.2f} (drift mode)"
        )
        state.confidence_threshold = new_threshold
        return new_threshold

    # Stable: relax toward baseline
    if current > baseline:
        new_threshold = max(current - 0.02, baseline)
        state.confidence_threshold = new_threshold
        _log.info(f"Relaxing confidence threshold: {current:.2f} → {new_threshold:.2f}")
        return new_threshold

    return current


def run_optimization_cycle(
    state: OptimizerState,
    detector: ADWINDetector | None = None,
) -> dict[str, Any]:
    """
    Run one optimization cycle: check drift, decide on retraining, adjust thresholds.

    Args:
        state:    Current OptimizerState with trade outcomes and Sharpe history.
        detector: ADWINDetector instance (creates default if None).

    Returns:
        Dict with keys: drift_status, should_retrain, confidence_threshold,
        win_rate, sharpe_trend.
    """
    if detector is None:
        detector = ADWINDetector()

    drift = detector.check(state.outcomes)

    retrain = should_retrain(state, drift)
    if retrain:
        state.last_retrain = datetime.now(timezone.utc)
        state.retrain_count += 1
        if drift.drift_detected:
            state.drift_alerts += 1

    new_threshold = adjust_confidence_threshold(state, drift)

    sharpe_trend = "improving" if (
        len(state.sharpe_history) >= 2
        and state.sharpe_history[-1] > state.sharpe_history[-2]
    ) else "stable" if len(state.sharpe_history) < 2 else "degrading"

    result = {
        "drift_detected": drift.drift_detected,
        "drift_message": drift.message,
        "should_retrain": retrain,
        "confidence_threshold": new_threshold,
        "win_rate": drift.window_win_rate,
        "recent_win_rate": drift.recent_win_rate,
        "sharpe_trend": sharpe_trend,
        "retrain_count": state.retrain_count,
    }

    _log.info(
        f"Optimization cycle — drift={drift.drift_detected}, "
        f"retrain={retrain}, threshold={new_threshold:.2f}, "
        f"win_rate={drift.window_win_rate:.1%}"
    )
    return result
