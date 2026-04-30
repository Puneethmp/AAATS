"""
Intraday vs overnight position limits for AAATS.

India NSE: enforces position closure before 3:15 PM IST in intraday mode.
Tracks overnight holding limits (max % of capital allowed to hold overnight).

Usage:
    from risk.overnight_manager import OvernightManager
    om = OvernightManager(market="india", max_overnight_pct=0.30)
    om.enforce_eod_closure(positions, client)  # call at 3:15 PM IST
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import pytz

from foundation.logger import get_logger

_log = get_logger("risk", "overnight_manager")

_IST = pytz.timezone("Asia/Kolkata")
_INTRADAY_CLOSE_HOUR = 15
_INTRADAY_CLOSE_MIN = 15  # Force close at 3:15 PM IST (15 min before market close)


class OvernightManager:
    """
    Manages intraday vs overnight position exposure.

    Args:
        market:             Target market.
        max_overnight_pct:  Max fraction of capital to hold overnight (0.0 = all intraday).
        intraday_only:      If True, force-close all positions before EOD.
    """

    def __init__(
        self,
        market: str,
        max_overnight_pct: float = 0.50,
        intraday_only: bool = False,
    ) -> None:
        self._market = market
        self._max_overnight_pct = max_overnight_pct
        self._intraday_only = intraday_only

    def should_force_close_for_eod(self) -> bool:
        """Return True if it's past the intraday close time and positions should be closed."""
        if self._market != "india" or not self._intraday_only:
            return False
        now = datetime.now(_IST)
        if now.weekday() >= 5:
            return False
        return (now.hour > _INTRADAY_CLOSE_HOUR or
                (now.hour == _INTRADAY_CLOSE_HOUR and now.minute >= _INTRADAY_CLOSE_MIN))

    def get_allowed_overnight_capital(self, total_capital: float) -> float:
        """Return maximum capital that can be held overnight."""
        return total_capital * self._max_overnight_pct

    def check_overnight_exposure(
        self,
        open_positions: list[dict],
        total_capital: float,
    ) -> list[str]:
        """
        Check if overnight exposure exceeds limit.
        Returns list of symbols that should be reduced to comply with overnight limit.
        """
        if self._intraday_only and self.should_force_close_for_eod():
            symbols = [p["symbol"] for p in open_positions]
            _log.warning(f"EOD force-close required for: {symbols}")
            return symbols

        total_exposure = sum(p["entry_price"] * p["shares"] for p in open_positions)
        max_overnight = self.get_allowed_overnight_capital(total_capital)

        if total_exposure > max_overnight:
            excess = total_exposure - max_overnight
            _log.warning(
                f"Overnight exposure {total_exposure:.0f} exceeds limit {max_overnight:.0f} "
                f"(excess: {excess:.0f})"
            )
            # Return symbols sorted by size (reduce largest first)
            by_size = sorted(open_positions, key=lambda p: p["entry_price"] * p["shares"], reverse=True)
            to_reduce = []
            reduced = 0.0
            for pos in by_size:
                to_reduce.append(pos["symbol"])
                reduced += pos["entry_price"] * pos["shares"]
                if reduced >= excess:
                    break
            return to_reduce

        return []
