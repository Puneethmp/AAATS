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
    