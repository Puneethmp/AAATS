"""Replay clock — driven by tape iteration, NOT wall clock.

Used by the runner to advance a deterministic notion of "now" to the
timestamp of each tape row. v5 modules that read wall clock during signal
generation would consult this clock instead; today the κ2 surface area
is bar-feature-only, so this clock is reserved for future expansion.
"""

from __future__ import annotations

from datetime import datetime, timezone

_NOW: datetime = datetime(2000, 1, 1, tzinfo=timezone.utc)


def set_now(dt: datetime) -> None:
    """Advance the replay clock. dt MUST be tz-aware."""
    global _NOW
    if dt.tzinfo is None:
        raise ValueError("set_now requires a timezone-aware datetime")
    _NOW = dt.astimezone(timezone.utc)


def now() -> datetime:
    """Replacement for `datetime.now(timezone.utc)`."""
    return _NOW


def now_naive() -> datetime:
    """Replacement for naive `datetime.now()`. Returns UTC time as naive."""
    return _NOW.replace(tzinfo=None)


def time_time() -> float:
    """Replacement for `time.time()`."""
    return _NOW.timestamp()
