"""
Market hours enforcement for AAATS.

Provides strict market hours checking for NSE (India) and other markets.
Crypto trades 24/7 and always returns True.

Usage:
    from execution.market_hours import is_market_open, get_next_open
    if not is_market_open("india"):
        return
"""

from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Literal

import pytz

from foundation.logger import get_logger

_log = get_logger("execution", "market_hours")

MarketType = Literal["crypto", "india", "us"]

_IST = pytz.timezone("Asia/Kolkata")
_ET = pytz.timezone("America/New_York")

# NSE schedule: Mon-Fri 09:15–15:30 IST
_NSE_OPEN = dtime(9, 15)
_NSE_CLOSE = dtime(15, 30)

# NYSE/NASDAQ: Mon-Fri 09:30–16:00 ET
_US_OPEN = dtime(9, 30)
_US_CLOSE = dtime(16, 0)


def is_market_open(market: MarketType) -> bool:
    """Return True if the given market is open right now."""
    if market == "crypto":
        return True

    if market == "india":
        now = datetime.now(_IST)
        if now.weekday() >= 5:
            return False
        t = now.time()
        result = _NSE_OPEN <= t <= _NSE_CLOSE
        if not result:
            _log.debug(f"NSE closed: current time {now.strftime('%H:%M IST')}")
        return result

    if market == "us":
        now = datetime.now(_ET)
        if now.weekday() >= 5:
            return False
        t = now.time()
        result = _US_OPEN <= t <= _US_CLOSE
        if not result:
            _log.debug(f"US market closed: current time {now.strftime('%H:%M ET')}")
        return result

    return False


def get_market_session(market: MarketType) -> str:
    """Return 'OPEN', 'PRE_MARKET', 'AFTER_HOURS', or 'CLOSED'."""
    if market == "crypto":
        return "OPEN"

    if market == "india":
        now = datetime.now(_IST)
        if now.weekday() >= 5:
            return "CLOSED"
        t = now.time()
        if t < dtime(9, 0):
            return "PRE_MARKET"
        if _NSE_OPEN <= t <= _NSE_CLOSE:
            return "OPEN"
        if t <= dtime(16, 0):
            return "AFTER_HOURS"
        return "CLOSED"

    if market == "us":
        now = datetime.now(_ET)
        if now.weekday() >= 5:
            return "CLOSED"
        t = now.time()
        if t < dtime(4, 0):
            return "CLOSED"
        if t < _US_OPEN:
            return "PRE_MARKET"
        if _US_OPEN <= t <= _US_CLOSE:
            return "OPEN"
        if t <= dtime(20, 0):
            return "AFTER_HOURS"
        return "CLOSED"

    return "CLOSED"


def require_market_open(market: MarketType) -> bool:
    """
    Log and return False if market is closed. Use as a guard at top of run_once().
    """
    if not is_market_open(market):
        session = get_market_session(market)
        _log.info(f"{market.upper()} market not open (session={session}) — skipping cycle")
        return False
    return True
