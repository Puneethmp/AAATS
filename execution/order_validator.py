"""
Order validator for AAATS.

Validates orders for:
  - Minimum order size (prevents tiny fills)
  - Notional value limits
  - Rate limiting (max orders per minute)
  - Liquidity check (order size vs. 24h volume)

Usage:
    from execution.order_validator import OrderValidator
    validator = OrderValidator(market="crypto")
    ok, reason = validator.validate(symbol="BTC/USDT", price=50000.0, shares=0.01, volume_24h=1e9)
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

from foundation.logger import get_logger

_log = get_logger("execution", "order_validator")


@dataclass
class ValidationResult:
    valid: bool
    reason: str


class OrderValidator:
    """
    Validates orders before submission to prevent bad fills and rate limit breaches.

    Args:
        market:            "crypto" or "india".
        min_notional_usd:  Minimum trade value (USD/USDT). Crypto: $10, India: ₹1000.
        max_notional_usd:  Maximum single trade value.
        max_orders_per_min: Rate limit guard.
        max_volume_pct:    Max order size as fraction of 24h volume (liquidity check).
    """

    _DEFAULTS = {
        "crypto": {"min_notional": 10.0, "max_notional": 50_000.0, "max_volume_pct": 0.001},
        "india": {"min_notional": 1_000.0, "max_notional": 10_00_000.0, "max_volume_pct": 0.005},
    }

    def __init__(
        self,
        market: str,
        max_orders_per_min: int = 30,
    ) -> None:
        self._market = market
        defaults = self._DEFAULTS.get(market, self._DEFAULTS["crypto"])
        self._min_notional = defaults["min_notional"]
        self._max_notional = defaults["max_notional"]
        self._max_vol_pct = defaults["max_volume_pct"]
        self._max_opm = max_orders_per_min
        self._order_times: deque[float] = deque(maxlen=200)

    def validate(
        self,
        symbol: str,
        price: float,
        shares: float,
        volume_24h: float = 0.0,
        side: str = "BUY",
    ) -> ValidationResult:
        """Validate an order. Returns (True, "OK") or (False, reason)."""
        notional = price * shares

        if notional < self._min_notional:
            return ValidationResult(False, f"Notional {notional:.2f} below minimum {self._min_notional}")

        if notional > self._max_notional:
            return ValidationResult(False, f"Notional {notional:.2f} exceeds maximum {self._max_notional}")

        if volume_24h > 0:
            vol_pct = notional / volume_24h
            if vol_pct > self._max_vol_pct:
                return ValidationResult(
                    False,
                    f"Order is {vol_pct:.4%} of 24h volume (limit: {self._max_vol_pct:.4%}) — liquidity risk",
                )

        # Rate limiting: count orders in past 60s
        now = time.time()
        self._order_times.append(now)
        recent = sum(1 for t in self._order_times if now - t < 60)
        if recent > self._max_opm:
            return ValidationResult(False, f"Rate limit: {recent} orders/min (max: {self._max_opm})")

        _log.debug(f"Order validated: {symbol} {side} {shares}@{price} notional={notional:.2f}")
        return ValidationResult(True, "OK")

    def reset_rate_limit(self) -> None:
        self._order_times.clear()
