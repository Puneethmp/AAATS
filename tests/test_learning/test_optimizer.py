"""Tests for learning/optimizer.py."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

import pytest

from learning.optimizer import (
    ADWINDetector,
    OptimizerState,
    _DRIFT_TOLERANCE,
    _MIN_SAMPLES_FOR_DRIFT,
    _RETRAIN_INTERVAL_DAYS,
    adjust_confidence_threshold,
    record_outcome,
    run_optimization_cycle,
    should_retrain,
    update_sharpe,
)


# ── ADWINDetector ──────────────────────────────────────────────────────────────

class TestADWINDetector:
    def test_insufficient_samples_no_drift(self):
        det = ADWINDetector()
        outcomes = deque([1, 0, 1])  # only 3 < 30
        status = det.check(outcomes)
        assert not status.drift_detected

    def test_stable_win_rate_no_drift(self):
        det = ADWINDetector(tolerance=0.15)
        # 40 outcomes with consistent ~60% win rate
        outcomes = deque([1, 0, 1, 1, 0] * 8)  # 60% win rate throughout
        status = det.check(outcomes)
        assert not status.drift_detected

    def test_sharp_drop_triggers_drift(self):
        det = ADWINDetector(tolerance=0.15, min_window=10)
        # First 30 outcomes = all wins; last 10 = all losses → big drift
        outcomes = deque([1] * 30 + [0] * 10)
        status = det.check(outcomes)
        assert status.drift_detected

    def test_delta_calculated_correctly(self):
        det = ADWINDetector(tolerance=0.15, min_window=10)
        outcomes = deque([1] * 30 + [0] * 10)
        status = det.check(outcomes)
        assert status.delta > 0
        assert status.window_win_rate != status.recent_win_rate

    def test_empty_outcomes_no_drift(self):
        det = ADWINDetector()
        status = det.check(deque())
        assert not status.drift_detected


# ── record_outcome / update_sharpe ────────────────────────────────────────────

class TestRecordAndUpdate:
    def test_record_win(self):
        state = OptimizerState()
        record_outcome(state, win=True)
        assert list(state.outcomes) == [1]

    def test_record_loss(self):
        state = OptimizerState()
        record_outcome(state, win=False)
        assert list(state.outcomes) == [0]

    def test_peak_sharpe_updates(self):
        state = OptimizerState()
        update_sharpe(state, 1.2)
        update_sharpe(state, 1.5)
        assert state.peak_sharpe == pytest.approx(1.5)

    def test_sharpe_history_appended(self):
        state = OptimizerState()
        update_sharpe(state, 1.0)
        update_sharpe(state, 1.3)
        assert len(state.sharpe_history) == 2

    def test_degradation_does_not_crash(self):
        state = OptimizerState()
        update_sharpe(state, 2.0)   # peak
        update_sharpe(state, 1.0)   # -50% → warning logged but no exception


# ── should_retrain ─────────────────────────────────────────────────────────────

class TestShouldRetrain:
    def _state_with_age(self, days: int) -> OptimizerState:
        state = OptimizerState()
        state.last_retrain = datetime.now(timezone.utc) - timedelta(days=days)
        return state

    def test_retrain_when_drift_detected(self):
        state = self._state_with_age(1)
        from learning.optimizer import DriftStatus
        drift = DriftStatus(drift_detected=True, window_win_rate=0.6, recent_win_rate=0.3,
                            delta=0.3, message="drift")
        assert should_retrain(state, drift)

    def test_retrain_after_7_days(self):
        state = self._state_with_age(8)
        from learning.optimizer import DriftStatus
        no_drift = DriftStatus(drift_detected=False, window_win_rate=0.6, recent_win_rate=0.6,
                               delta=0.0, message="stable")
        assert should_retrain(state, no_drift)

    def test_no_retrain_within_7_days(self):
        state = self._state_with_age(3)
        from learning.optimizer import DriftStatus
        no_drift = DriftStatus(drift_detected=False, window_win_rate=0.6, recent_win_rate=0.6,
                               delta=0.0, message="stable")
        assert not should_retrain(state, no_drift)


# ── adjust_confidence_threshold ───────────────────────────────────────────────

class TestAdjustThreshold:
    def test_drift_raises_threshold(self):
        state = OptimizerState()
        state.confidence_threshold = 0.60
        from learning.optimizer import DriftStatus
        drift = DriftStatus(drift_detected=True, window_win_rate=0.5, recent_win_rate=0.3,
                            delta=0.2, message="drift")
        new_t = adjust_confidence_threshold(state, drift)
        assert new_t > 0.60

    def test_no_drift_relaxes_elevated_threshold(self):
        state = OptimizerState()
        state.confidence_threshold = 0.68  # elevated
        from learning.optimizer import DriftStatus
        no_drift = DriftStatus(drift_detected=False, window_win_rate=0.6, recent_win_rate=0.6,
                               delta=0.0, message="stable")
        new_t = adjust_confidence_threshold(state, no_drift)
        assert new_t < 0.68

    def test_threshold_capped_at_max(self):
        state = OptimizerState()
        state.confidence_threshold = 0.69  # near max
        from learning.optimizer import DriftStatus
        drift = DriftStatus(drift_detected=True, window_win_rate=0.4, recent_win_rate=0.2,
                            delta=0.2, message="drift")
        new_t = adjust_confidence_threshold(state, drift)
        assert new_t <= 0.70  # max = baseline + 0.10 = 0.70


# ── run_optimization_cycle ────────────────────────────────────────────────────

class TestRunOptimizationCycle:
    def test_returns_expected_keys(self):
        state = OptimizerState()
        for _ in range(35):
            record_outcome(state, win=True)
        result = run_optimization_cycle(state)
        assert "drift_detected" in result
        assert "should_retrain" in result
        assert "confidence_threshold" in result
        assert "win_rate" in result

    def test_retrain_count_increments(self):
        state = OptimizerState()
        # Set last_retrain to 8 days ago to force weekly retrain
        state.last_retrain = datetime.now(timezone.utc) - timedelta(days=8)
        for _ in range(35):
            record_outcome(state, win=True)
        run_optimization_cycle(state)
        assert state.retrain_count == 1

    def test_sharpe_trend_improving(self):
        state = OptimizerState()
        update_sharpe(state, 1.0)
        update_sharpe(state, 1.5)
        for _ in range(35):
            record_outcome(state, win=True)
        result = run_optimization_cycle(state)
        assert result["sharpe_trend"] == "improving"

    def test_no_crash_with_empty_state(self):
        state = OptimizerState()
        result = run_optimization_cycle(state)
        assert isinstance(result, dict)
