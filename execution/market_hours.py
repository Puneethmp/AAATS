"""
Market hours enforcement for AAATS.

Provides strict market hours checking for NSE (India) and other markets.
Crypto trades 24/7 and always returns True.

Includes NSE holiday calendar for 2025-2027 (official BSE/NSE schedule).
Auto-rejects on public holidays so the scheduler doesn't fire on Diwali, etc.

Usage:
    from execution.market_hours import is_market_open, get_next_open
    if not is_market_open("india"):
        return
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime
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

# ── NSE Official Holiday Calendar 2025–2027 ───────────────────────────────────
# Source: NSE India official trading holiday schedule
# Muhurat trading sessions (Diwali evening) are NOT included — too short to trade
_NSE_HOLIDAYS: frozenset[date] = frozenset({
    # 2025
    date(2025, 1, 26),   # Republic Day
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramzan)
    date(2025, 4, 10),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 14),   # Ram Navami / Good Friday
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Dussehra
    date(2025, 10, 2),   # Gandhi Jayanti
    date(2025, 10, 24),  # Diwali (Laxmi Pujan)
    date(2025, 11, 5),   # Gurunanak Jayanti
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Mahashivratri
    date(2026, 3, 20),   # Holi (Dhuleta)
    date(2026, 3, 31),   # Id-Ul-Fitr
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 9, 17),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra (Vijaya Dashami)
    date(2026, 11, 8),   # Diwali (Laxmi Pujan)
    date(2026, 11, 24),  # Gurunanak Jayanti
    date(2026, 12, 25),  # Christmas
    # 2027
    date(2027, 1, 26),   # Republic Day
    date(2027, 2, 21),   # Mahashivratri
    date(2027, 3, 10),   # Holi
    date(2027, 3, 19),   # Id-Ul-Fitr
    date(2027, 3, 26),   # Good Friday
    date(2027, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2027, 5, 1),    # Maharashtra Day
    date(2027, 8, 15),   # Independence Day
    date(2027, 9, 6),    # Ganesh Chaturthi
    date(2027, 10, 2),   # Gandhi Jayanti
    date(2027, 10, 27),  # Diwali (Laxmi Pujan)
    date(2027, 11, 13),  # Gurunanak Jayanti
    date(2027, 12, 25),  # Christmas
})


def is_nse_holiday(d: date | None = None) -> bool:
    """Return True if the given date (default=today IST) is an NSE holiday."""
    if d is None:
        d = datetime.now(_IST).date()
    return d in _NSE_HOLIDAYS


def is_market_open(market: MarketType) -> bool:
    """Return True if the given market is open right now."""
    if market == "crypto":
        return True

    if market == "india":
        now = datetime.now(_IST)
        if now.weekday() >= 5:
            _log.debug(f"NSE closed: weekend ({now.strftime('%A')})")
            return False
        if is_nse_holiday(now.date()):
            _log.info(f"NSE closed: public holiday ({now.date()})")
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
    date(2027, 8, 15),   # Independence Day
    date(2027, 9, 6),    # 