"""Tests for trading/live_loop.py — live trading safety gates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading.live_loop import (
    LiveTradingConfig,
    LiveTradingState,
    TradingMode,
    TwoStepActivationError,
    confirm_live_step_1,
    confirm_live_step_2,
    get_position_scale,
    maybe_graduate,
    revert_to_paper,
    should_graduate_to_full,
)


class TestConfirmLiveStep1:
    def test_correct_phrase_moves_to_pending(self):
        state = LiveTradingState()
        confirm_live_step_1(state, "I UNDERSTAND REAL MONEY IS AT RISK")
        assert state.mode == TradingMode.PENDING_LIVE

    def test_wrong_phrase_raises(self):
        state = LiveTradingState()
        with pytest.raises(TwoStepActivationError):
            confirm_live_step_1(state, "yes please enable live")

    def test_cannot_activate_if_already_live(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_MICRO
        with pytest.raises(TwoStepActivationError):
            confirm_live_step_1(state, "I UNDERSTAND REAL MONEY IS AT RISK")


class TestConfirmLiveStep2:
    def _pending_state(self) -> LiveTradingState:
        state = LiveTradingState()
        state.mode = TradingMode.PENDING_LIVE
        state.step1_confirmed_at = datetime.now(timezone.utc)
        return state

    def test_correct_phrase_enables_live_micro(self):
        state = self._pending_state()
        confirm_live_step_2(state, "ENABLE LIVE TRADING NOW")
        assert state.mode == TradingMode.LIVE_MICRO

    def test_wrong_phrase_raises(self):
        state = self._pending_state()
        with pytest.raises(TwoStepActivationError):
            confirm_live_step_2(state, "go live")

    def test_timeout_reverts_to_paper(self):
        state = self._pending_state()
        # Force expiry by backdating step1
        state.step1_confirmed_at = datetime.now(timezone.utc) - timedelta(seconds=400)
        with pytest.raises(TwoStepActivationError, match="expired"):
            confirm_live_step_2(state, "ENABLE LIVE TRADING NOW")
        assert state.mode == TradingMode.PAPER

    def test_requires_pending_live_state(self):
        state = LiveTradingState()  # PAPER mode
        with pytest.raises(TwoStepActivationError):
            confirm_live_step_2(state, "ENABLE LIVE TRADING NOW")

    def test_sets_live_start_date(self):
        state = self._pending_state()
        confirm_live_step_2(state, "ENABLE LIVE TRADING NOW")
        assert state.live_start_date is not None


class TestRevertToPaper:
    def test_reverts_from_live_micro(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_MICRO
        revert_to_paper(state, "test revert")
        assert state.mode == TradingMode.PAPER

    def test_reverts_from_live_full(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_FULL
        revert_to_paper(state, "manual override")
        assert state.mode == TradingMode.PAPER


class TestGetPositionScale:
    def test_paper_returns_zero(self):
        state = LiveTradingState()
        assert get_position_scale(state) == 0.0

    def test_micro_returns_one_percent(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_MICRO
        assert get_position_scale(state) == pytest.approx(0.01)

    def test_full_returns_one(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_FULL
        assert get_position_scale(state) == 1.0

    def test_pending_returns_zero(self):
        state = LiveTradingState()
        state.mode = TradingMode.PENDING_LIVE
        assert get_position_scale(state) == 0.0


class TestGraduation:
    def test_graduates_after_criteria_met(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_MICRO
        state.live_start_date = datetime.now(timezone.utc) - timedelta(days=31)
        state.live_pnl = 500.0
        config = LiveTradingConfig(graduation_days=30)
        assert should_graduate_to_full(state, config)

    def test_no_graduation_if_losing(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_MICRO
        state.live_start_date = datetime.now(timezone.utc) - timedelta(days=31)
        state.live_pnl = -100.0
        assert not should_graduate_to_full(state, LiveTradingConfig())

    def test_no_graduation_before_30_days(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_MICRO
        state.live_start_date = datetime.now(timezone.utc) - timedelta(days=15)
        state.live_pnl = 500.0
        assert not should_graduate_to_full(state, LiveTradingConfig())

    def test_maybe_graduate_promotes_mode(self):
        state = LiveTradingState()
        state.mode = TradingMode.LIVE_MICRO
        state.live_start_date = datetime.now(timezone.utc) - timedelta(days=31)
        state.live_pnl = 500.0
        promoted = maybe_graduate(state, LiveTradingConfig())
        assert promoted
        assert state.mode == TradingMode.LIVE_FULL
