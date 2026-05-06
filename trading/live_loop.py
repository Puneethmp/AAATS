"""
Live Trading Skeleton for AAATS.

IMPORTANT: This module is a skeleton only. All execution is gated behind
explicit confirmation steps. Real money is never deployed accidentally.

Safety architecture:
  1. Default mode is PAPER — live mode requires explicit activation.
  2. Live activation requires two separate confirmations (2-step gate).
  3. Initial live positions are micro-sized (1% of normal size).
  4. Full position sizing only after 30 days of profitable live trading.
  5. Kill switches (risk/engine.py) apply equally to paper and live.

State machine:
  PAPER → (confirm_step_1) → PENDING_LIVE →
  (confirm_step_2 within 5 min) → LIVE_MICRO →
  (30 days + profitable) → LIVE_FULL
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from foundation.logger import get_logger
from risk.engine import RiskDecision, RiskEngine

_log = get_logger("trading", "live_loop")


class TradingMode(Enum):
    PAPER = "paper"
    PENDING_LIVE = "pending_live"    # 1st confirmation done; awaiting 2nd
    LIVE_MICRO = "live_micro"        # 1% position sizing
    LIVE_FULL = "live_full"          # full position sizing


_MICRO_SCALE = 0.01   # 1% of normal size during live micro phase
_LIVE_GRADUATION_DAYS = 30  # days of profitable live trading before full size


@dataclass
class LiveTradingConfig:
    initial_capital: float = 0.0
    micro_scale: float = _MICRO_SCALE
    graduation_days: int = _LIVE_GRADUATION_DAYS


@dataclass
class LiveTradingState:
    mode: TradingMode = TradingMode.PAPER
    step1_confirmed_at: datetime | None = None
    step2_confirmed_at: datetime | None = None
    live_start_date: datetime | None = None
    live_trade_count: int = 0
    live_pnl: float = 0.0
    _pending_timeout_seconds: int = 300  # 5 min window for step 2

    def is_confirmation_expired(self) -> bool:
        if self.step1_confirmed_at is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self.step1_confirmed_at).total_seconds()
        return elapsed > self._pending_timeout_seconds

    def days_live(self) -> float:
        if self.live_start_date is None:
            return 0.0
        return (datetime.now(timezone.utc) - self.live_start_date).total_seconds() / 86400


class TwoStepActivationError(Exception):
    """Raised when live activation steps are violated."""


def confirm_live_step_1(state: LiveTradingState, confirmation_phrase: str) -> str:
    """
    First step to enable live trading.

    Args:
        state:               Current LiveTradingState.
        confirmation_phrase: Must be "I UNDERSTAND REAL MONEY IS AT RISK".

    Returns:
        Status message.

    Raises:
        TwoStepActivationError: If wrong phrase or already in live mode.
    """
    _REQUIRED = "I UNDERSTAND REAL MONEY IS AT RISK"

    if state.mode in (TradingMode.LIVE_MICRO, TradingMode.LIVE_FULL):
        raise TwoStepActivationError("Already in live trading mode.")

    if confirmation_phrase != _REQUIRED:
        raise TwoStepActivationError(
            f"Wrong confirmation phrase. Required: '{_REQUIRED}'"
        )

    state.mode = TradingMode.PENDING_LIVE
    state.step1_confirmed_at = datetime.now(timezone.utc)
    _log.warning("Live trading step 1 confirmed — waiting for step 2 (5 min window)")
    return "Step 1 confirmed. Now call confirm_live_step_2() within 5 minutes."


def confirm_live_step_2(state: LiveTradingState, confirmation_phrase: str) -> str:
    """
    Second step to enable live trading. Must be called within 5 minutes of step 1.

    Args:
        state:               Current LiveTradingState.
        confirmation_phrase: Must be "ENABLE LIVE TRADING NOW".

    Returns:
        Status message.

    Raises:
        TwoStepActivationError: If timeout expired, wrong phrase, or wrong state.
    """
    _REQUIRED = "ENABLE LIVE TRADING NOW"

    if state.mode != TradingMode.PENDING_LIVE:
        raise TwoStepActivationError(
            "Step 2 requires PENDING_LIVE state. Call confirm_live_step_1 first."
        )

    if state.is_confirmation_expired():
        state.mode = TradingMode.PAPER
        state.step1_confirmed_at = None
        raise TwoStepActivationError(
            "Confirmation expired (5 min window). Start over with step 1."
        )

    if confirmation_phrase != _REQUIRED:
        raise TwoStepActivationError(
            f"Wrong confirmation phrase. Required: '{_REQUIRED}'"
        )

    state.mode = TradingMode.LIVE_MICRO
    state.step2_confirmed_at = datetime.now(timezone.utc)
    state.live_start_date = datetime.now(timezone.utc)
    _log.warning(
        "LIVE TRADING ENABLED — MICRO MODE (1% position sizing). "
        "Full sizing after 30 profitable days."
    )
    return "Live trading enabled in MICRO mode (1% position size). Monitor closely."


def revert_to_paper(state: LiveTradingState, reason: str) -> None:
    """Immediately revert to paper trading mode."""
    previous = state.mode
    state.mode = TradingMode.PAPER
    _log.warning(f"Reverted from {previous.value} to PAPER mode — reason: {reason}")


def get_position_scale(state: LiveTradingState) -> float:
    """
    Return the position size multiplier for the current mode.

    Returns:
        0.0 for PAPER (no real money)
        micro_scale (0.01) for LIVE_MICRO
        1.0 for LIVE_FULL
    """
    if state.mode == TradingMode.PAPER:
        return 0.0   # Paper: execution layer uses paper prices, not real
    if state.mode == TradingMode.LIVE_MICRO:
        return _MICRO_SCALE
    if state.mode == TradingMode.LIVE_FULL:
        return 1.0
    return 0.0  # PENDING_LIVE: no orders yet


def should_graduate_to_full(state: LiveTradingState, config: LiveTradingConfig) -> bool:
    """
    Check whether micro mode has earned graduation to full sizing.

    Criteria:
      - >= 30 days in live mode
      - Positive total PnL

    Returns:
        True if graduation criteria met.
    """
    if state.mode != TradingMode.LIVE_MICRO:
        return False
    return (
        state.days_live() >= config.graduation_days
        and state.live_pnl > 0
    )


def maybe_graduate(state: LiveTradingState, config: LiveTradingConfig) -> bool:
    """
    Promote to LIVE_FULL if graduation criteria are met.

    Returns:
        True if promoted.
    """
    if should_graduate_to_full(state, config):
        state.mode = TradingMode.LIVE_FULL
        _log.warning(
            f"Graduated to LIVE_FULL mode after {state.days_live():.1f} days, "
            f"PnL={state.live_pnl:+.2f}"
        )
        return True
    return False
