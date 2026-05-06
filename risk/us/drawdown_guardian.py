"""
Drawdown guardian for AAATS markets.

Tracks a rolling peak portfolio value and triggers kill_switch.halt() when
drawdown crosses circuit-breaker thresholds defined in Section 7 of the blueprint.

Thresholds:
    MARKET_DRAWDOWN_HALT_PCT = -15%   triggers halt for that market
    TOTAL_DRAWDOWN_HALT_PCT  = -20%   triggers halt for all markets (use market="all")

State is in-memory only — does not survive process restarts. The kill switch halt
flag (persisted to disk by kill_switch.halt) IS durable across restarts.

Once halted, update() always returns halted=True. Recovery alone never resumes
trading — only reset() after human review can clear the guardian's internal flag.
"""

from dataclasses import dataclass

import foundation.kill_switch as kill_switch
from foundation.logger import get_logger

# ── Named constants ────────────────────────────────────────────────────────────
MARKET_DRAWDOWN_HALT_PCT = -0.15  # -15% per market → halt that market
TOTAL_DRAWDOWN_HALT_PCT = -0.20  # -20% total portfolio → halt all

log = get_logger(market="us", module="drawdown_guardian")


@dataclass
class DrawdownStatus:
    """Snapshot of drawdown state returned by DrawdownGuardian.update()."""

    current_value: float
    peak_value: float
    drawdown_pct: float  # 0.0 or negative; -0.10 = 10% drawdown
    halted: bool
    halt_reason: str | None  # None unless halted


class DrawdownGuardian:
    """
    Monitors rolling peak portfolio value and halts when drawdown exceeds threshold.

    Instantiate once per market (or once for total portfolio with market="all").
    Market-level instances use MARKET_DRAWDOWN_HALT_PCT (-15%).
    Total portfolio instance uses TOTAL_DRAWDOWN_HALT_PCT (-20%).

    Once halted, the guardian stays halted until reset() is called after human
    review. The kill switch halt (persisted to disk) must also be cleared
    separately via kill_switch.reset().
    """

    def __init__(self, peak_value: float, market: str) -> None:
        """
        Args:
            peak_value: Starting portfolio value used as the initial peak.
            market: Market to halt when threshold is crossed. Pass "us", "india",
                    or "crypto" for market-level guarding; pass "all" for total
                    portfolio guarding (uses TOTAL_DRAWDOWN_HALT_PCT threshold).

        Raises:
            ValueError: If peak_value is not positive.
        """
        if peak_value <= 0:
            raise ValueError(f"peak_value must be > 0, got {peak_value}")

        self._peak_value: float = peak_value
        self._current_value: float = peak_value
        self._market: str = market
        self._halted: bool = False
        self._halt_reason: str | None = None
        self._halt_threshold: float = (
            TOTAL_DRAWDOWN_HALT_PCT if market == "all" else MARKET_DRAWDOWN_HALT_PCT
        )

        log.info(
            "DrawdownGuardian initialised",
            market=market,
            peak_value=peak_value,
            halt_threshold=self._halt_threshold,
        )

    def update(self, current_value: float) -> DrawdownStatus:
        """
        Record the latest portfolio value and check drawdown against threshold.

        Peak is a rolling high-water mark — it moves up on new highs but never down.
        If already halted, returns halted=True without re-calling kill_switch.

        Args:
            current_value: Current total market allocation value (same currency
                           as peak_value).

        Returns:
            DrawdownStatus with current drawdown and halt state.
        """
        self._current_value = current_value

        # Sticky halt — stay halted regardless of recovery
        if self._halted:
            drawdown_pct = (current_value - self._peak_value) / self._peak_value
            return DrawdownStatus(
                current_value=current_value,
                peak_value=self._peak_value,
                drawdown_pct=drawdown_pct,
                halted=True,
                halt_reason=self._halt_reason,
            )

        # Rolling peak: only moves up, never down
        if current_value > self._peak_value:
            self._peak_value = current_value
            log.debug(
                "New peak recorded",
                market=self._market,
                new_peak=self._peak_value,
            )

        drawdown_pct = (current_value - self._peak_value) / self._peak_value

        log.debug(
            "Drawdown check",
            market=self._market,
            current_value=current_value,
            peak_value=self._peak_value,
            drawdown_pct=f"{drawdown_pct:.4%}",
            threshold=self._halt_threshold,
        )

        if drawdown_pct <= self._halt_threshold:
            self._halted = True
            self._halt_reason = (
                f"Drawdown {drawdown_pct:.2%} breached {self._halt_threshold:.2%} "
                f"circuit-breaker threshold for market '{self._market}'"
            )
            log.warning(
                "Drawdown circuit breaker triggered",
                market=self._market,
                drawdown_pct=drawdown_pct,
                threshold=self._halt_threshold,
                reason=self._halt_reason,
            )
            kill_switch.halt(
                market=self._market,
                reason=self._halt_reason,
                triggered_by="drawdown_guardian",
            )
            return DrawdownStatus(
                current_value=current_value,
                peak_value=self._peak_value,
                drawdown_pct=drawdown_pct,
                halted=True,
                halt_reason=self._halt_reason,
            )

        return DrawdownStatus(
            current_value=current_value,
            peak_value=self._peak_value,
            drawdown_pct=drawdown_pct,
            halted=False,
            halt_reason=None,
        )

    def current_drawdown(self) -> float:
        """
        Return the current drawdown percentage relative to the rolling peak.

        Returns:
            A non-positive float. 0.0 means no drawdown.
            -0.10 represents a 10% drawdown from peak.
        """
        return (self._current_value - self._peak_value) / self._peak_value

    def is_halted(self) -> bool:
        """Return True if the guardian has triggered a halt."""
        return self._halted

    def reset(self) -> None:
        """
        Clear the halt state after human review.

        Resets the internal peak to the most recent portfolio value so drawdown
        tracking restarts from the current level. Does NOT clear the kill_switch
        halt flag — that requires a separate call to kill_switch.reset().
        """
        prev_peak = self._peak_value
        self._halted = False
        self._halt_reason = None
        self._peak_value = self._current_value

        log.info(
            "DrawdownGuardian reset",
            market=self._market,
            previous_peak=prev_peak,
            new_peak=self._peak_value,
        )
