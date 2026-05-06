"""
Dynamic position sizer for AAATS.

Sizes positions based on:
  - Kelly Criterion (half-Kelly for safety)
  - Volatility scaling (ATR-based)
  - Portfolio heat limit (max total risk in % of capital)

Usage:
    from risk.position_sizer import PositionSizer
    sizer = PositionSizer(capital=500_000.0)
    shares = sizer.calculate_position_size(
        price=1800.0, atr=45.0, win_rate=0.52, avg_win=0.03, avg_loss=0.02
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from foundation.logger import get_logger

_log = get_logger("risk", "position_sizer")


@dataclass
class SizeResult:
    shares: float
    position_value: float
    risk_pct: float
    method: str


class PositionSizer:
    """
    Calculates position size using Kelly Criterion with ATR-based stops.

    Args:
        capital:         Total trading capital (INR or USDT).
        max_position_pct: Max single position as fraction of capital (default 5%).
        max_portfolio_heat: Max total risk across all open positions (default 20%).
        kelly_fraction:  Safety factor — 0.5 = half-Kelly (default).
    """

    def __init__(
        self,
        capital: float,
        max_position_pct: float = 0.05,
        max_portfolio_heat: float = 0.20,
        kelly_fraction: float = 0.5,
    ) -> None:
        self._capital = capital
        self._max_pos_pct = max_position_pct
        self._max_heat = max_portfolio_heat
        self._kelly_frac = kelly_fraction
        self._current_heat: float = 0.0

    def calculate_position_size(
        self,
        price: float,
        atr: float,
        win_rate: float = 0.5,
        avg_win: float = 0.03,
        avg_loss: float = 0.02,
    ) -> SizeResult:
        """
        Returns optimal shares to buy.

        Args:
            price:    Current market price.
            atr:      14-period ATR (used to set stop distance).
            win_rate: Historical win probability (0-1).
            avg_win:  Average win as fraction of price.
            avg_loss: Average loss as fraction of price (positive number).
        """
        if price <= 0 or atr <= 0:
            return SizeResult(shares=0.0, position_value=0.0, risk_pct=0.0, method="zero_price")

        # Kelly fraction: f = (p*b - q) / b where b = avg_win/avg_loss
        b = avg_win / max(avg_loss, 1e-9)
        q = 1 - win_rate
        kelly_f = (win_rate * b - q) / b
        kelly_f = max(0.0, kelly_f) * self._kelly_frac

        # ATR-based stop loss: 2x ATR below entry
        stop_distance = 2.0 * atr
        risk_per_share = stop_distance
        max_risk_amount = self._capital * min(kelly_f, self._max_pos_pct)
        shares_by_risk = max_risk_amount / max(risk_per_share, 1e-9)

        # Cap to max position pct
        max_shares_by_pct = (self._capital * self._max_pos_pct) / price
        shares = min(shares_by_risk, max_shares_by_pct)

        # Check portfolio heat
        position_risk_pct = (shares * risk_per_share) / self._capital
        if self._current_heat + position_risk_pct > self._max_heat:
            available_heat = max(0.0, self._max_heat - self._current_heat)
            shares = (available_heat * self._capital) / max(risk_per_share, 1e-9)
            method = "heat_limited"
        else:
            method = "kelly"

        shares = max(0.0, shares)
        pos_value = shares * price
        risk_pct = (shares * risk_per_share) / self._capital

        _log.debug(
            f"Position size: {shares:.4f} shares @ {price:.2f} "
            f"| value={pos_value:.0f} | risk={risk_pct:.2%} | method={method}"
        )
        return SizeResult(shares=shares, position_value=pos_value, risk_pct=risk_pct, method=method)

    def add_position_heat(self, risk_pct: float) -> None:
        self._current_heat = min(self._max_heat, self._current_heat + risk_pct)

    def remove_position_heat(self, risk_pct: float) -> None:
        self._current_heat = max(0.0, self._current_heat - risk_pct)

    def update_capital(self, new_capital: float) -> None:
        self._capital = new_capital
