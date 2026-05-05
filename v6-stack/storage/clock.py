"""Clock helpers — UTC wall-clock + monotonic.

Per κ1 requirement 9:
  - UTC everywhere (no naive datetimes; TIMESTAMPTZ in storage).
  - Monotonic timestamps in parity logs.
  - NTP sync verification helper (advisory; called from health probe).

Convention:
  - utc_now() returns timezone-aware UTC datetime — use for stored timestamps.
  - utc_now_ts() returns float Unix epoch seconds (UTC) — use where v5 stored REAL.
  - monotonic_ns() is the kernel monotonic counter — use for duration measurement.
  - parity_stamp() returns a (utc_iso, monotonic_ns) tuple — emit into shadow logs.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware UTC `datetime`. Always use this in DB writes."""
    return datetime.now(timezone.utc)


def utc_now_ts() -> float:
    """UTC unix epoch as float seconds. Parity with v5's REAL timestamps."""
    return utc_now().timestamp()


def utc_now_iso() -> str:
    """ISO8601 UTC string with timezone."""
    return utc_now().isoformat()


def monotonic_ns() -> int:
    """Kernel monotonic counter, nanoseconds. Use for duration / cycle measurement."""
    return time.monotonic_ns()


@dataclass(frozen=True, slots=True)
class ParityStamp:
    """Pair of clock readings emitted alongside parity-log events.

    `wall_utc_iso`  — wall-clock ISO8601 UTC (canonical timestamp).
    `monotonic_ns`  — kernel monotonic counter at the same instant.

    Both are logged in shadow-mode events so we can detect clock skew between
    v5 and v6 hosts without contaminating the data with NTP-jump artefacts.
    """
    wall_utc_iso: str
    monotonic_ns: int


def parity_stamp() -> ParityStamp:
    return ParityStamp(wall_utc_iso=utc_now_iso(), monotonic_ns=monotonic_ns())


def verify_ntp_sync(timeout_s: float = 2.0) -> tuple[bool, str]:
    """Advisory check: is `chronyd` (or systemd-timesyncd) reporting a healthy sync?

    Returns (synced, detail). Best-effort — used as a soft probe in health
    endpoints, NOT as a gate. Designed to never block; on any error returns
    (False, reason). The helper makes no system changes.
    """
    if os.name != "posix":
        return True, "non-posix host (no NTP probe)"
    try:
        proc = subprocess.run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=timeout_s,
        )
        out = (proc.stdout or "").strip().lower()
        if proc.returncode == 0 and out == "yes":
            return True, "timedatectl: synchronized=yes"
        return False, f"timedatectl: synchronized={out!r} (rc={proc.returncode})"
    except FileNotFoundError:
        return False, "timedatectl not available"
    except subprocess.TimeoutExpired:
        return False, f"timedatectl: timeout after {timeout_s}s"
    except Exception as e:  # noqa: BLE001
        return False, f"timedatectl: {e!r}"
