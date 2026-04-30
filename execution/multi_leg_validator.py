"""
Multi-leg order validator for AAATS.

Validates spread trades, pairs trades, and complex multi-leg orders
before submission. Checks that all legs are valid and risk-controlled.

Usage:
    from execution.multi_leg_validator import MultiLegValidator, OrderLeg
    validator = MultiLegValidator()
    legs = [
        OrderLeg("BUY", "BTC/USDT", 0.01, 50000),
        OrderLeg("SELL", "ETH/USDT", 0.15, 3000),
    ]
    ok, reason = validator.validate_legs(legs)
"""

from __future__ import annotations

from dataclasses import dataclass
from foundation.logger import get_logger

_log = get_logger("execution", "multi_leg_validator")


@dataclass
class OrderLeg:
    side: str          # "BUY" or "SELL"
    symbol: str
    shares: float
    price: float
    market: str = "crypto"

    @property
    def notional(self) -> float:
        return self.shares * self.price


class MultiLegValidator:
    """
    Validates multi-leg orders for complex strategies (pairs, spreads, etc.)

    Args:
        max_legs:         Maximum number of legs per order.
        max_net_notional: Maximum net exposure across all legs (absolute value).
        require_hedge:    If True, require buy and sell legs to balance within tolerance.
        hedge_tolerance:  Maximum imbalance fraction (default 20%).
    """

    def __init__(
        self,
        max_legs: int = 4,
        max_net_notional: float = 100_000.0,
        require_hedge: bool = False,
        hedge_tolerance: float = 0.20,
    ) -> None:
        self._max_legs = max_legs
        self._max_net_notional = max_net_notional
        self._require_hedge = require_hedge
        self._hedge_tol = hedge_tolerance

    def validate_legs(self, legs: list[OrderLeg]) -> tuple[bool, str]:
        """Validate a multi-leg order. Returns (valid, reason)."""
        if not legs:
            return False, "No legs provided"

        if len(legs) > self._max_legs:
            return False, f"Too many legs: {len(legs)} > max {self._max_legs}"

        for i, leg in enumerate(legs):
            if leg.shares <= 0:
                return False, f"Leg {i}: shares must be positive, got {leg.shares}"
            if leg.price <= 0:
                return False, f"Leg {i}: price must be positive, got {leg.price}"
            if leg.side not in ("BUY", "SELL"):
                return False, f"Leg {i}: side must be BUY or SELL, got {leg.side}"

        buy_notional = sum(l.notional for l in legs if l.side == "BUY")
        sell_notional = sum(l.notional for l in legs if l.side == "SELL")
        net = buy_notional - sell_notional

        if abs(net) > self._max_net_notional:
            return False, f"Net notional {abs(net):.0f} exceeds limit {self._max_net_notional:.0f}"

        if self._require_hedge and legs:
            total = buy_notional + sell_notional
            if total > 0:
                imbalance = abs(net) / total
                if imbalance > self._hedge_tol:
                    return False, (
                        f"Hedge imbalance {imbalance:.1%} exceeds tolerance {self._hedge_tol:.1%} "
                        f"(buy={buy_notional:.0f}, sell={sell_notional:.0f})"
                    )

        _log.debug(
            f"Multi-leg order validated: {len(legs)} legs | "
            f"net={net:.0f} | buy={buy_notional:.0f} | sell={sell_notional:.0f}"
        )
        return True, "OK"
