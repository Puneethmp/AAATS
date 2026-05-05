"""Clock invariants (κ1 req 9): UTC everywhere, monotonic stamps emitted."""

from __future__ import annotations

import time
from datetime import timezone

import pytest

from storage import clock


def test_utc_now_is_tz_aware_utc():
    dt = clock.utc_now()
    assert dt.tzinfo is not None
    assert dt.tzinfo.utcoffset(dt) == timezone.utc.utcoffset(dt)


def test_iso_string_includes_tz():
    s = clock.utc_now_iso()
    assert "+00:00" in s or s.endswith("Z")


def test_monotonic_strictly_increasing():
    a = clock.monotonic_ns()
    time.sleep(0.001)
    b = clock.monotonic_ns()
    assert b > a


def test_parity_stamp_pairs_clocks():
    p = clock.parity_stamp()
    assert isinstance(p.wall_utc_iso, str)
    assert isinstance(p.monotonic_ns, int)
    assert p.monotonic_ns > 0
    assert "+00:00" in p.wall_utc_iso or p.wall_utc_iso.endswith("Z")


def test_verify_ntp_sync_returns_tuple():
    """verify_ntp_sync is best-effort and must never raise."""
    ok, detail = clock.verify_ntp_sync()
    assert isinstance(ok, bool)
    assert isinstance(detail, str)
