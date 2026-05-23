"""Tests for D.5 soak counter + anomaly-window logic.

Per Cowork D1 (2026-05-23): the D.5 30-day soak counter PAUSES during
defined anomaly windows and resumes on the next NONE-NONE digest.
Strict reading would invalidate the soak on any infrastructure
incident; pragmatic reading preserves it while still penalizing real
trading-side problems.

Five required cases per the session-12 prompt:
  - test_counter_excludes_digest_in_anomaly_window
  - test_counter_resumes_after_anomaly_window_closes
  - test_marker_has_anomaly_windows_field
  - test_open_anomaly_window_closes_on_next_NONE_digest
  - test_multiple_anomaly_windows_compose_correctly
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from monitoring import daily_digest as dd


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def cfg(tmp_path: Path) -> dd.DigestConfig:
    """A DigestConfig pointing at tmp_path so each test is isolated."""
    return dd.DigestConfig.from_data_dir(tmp_path)


def _write_marker(
    data_dir: Path,
    *,
    day1_at: datetime,
    anomaly_windows: list[dict] | None = None,
) -> dict:
    marker = {
        "day1_at": day1_at.isoformat(),
        "starting_equity_usd": 200.0,
        "divergence_watcher_armed": True,
        "watcher_window_days": 7,
        "c3_threshold_low_usd": -2.0,
        "c3_threshold_high_usd": 2.0,
    }
    if anomaly_windows is not None:
        marker["anomaly_windows"] = anomaly_windows
    (data_dir / dd.WATCHER_MARKER_FILENAME).write_text(
        json.dumps(marker, indent=2), encoding="utf-8",
    )
    return marker


def _write_digest_log(
    data_dir: Path, entries: list[dict],
) -> None:
    (data_dir / "digest_log.json").write_text(
        json.dumps(entries, indent=2), encoding="utf-8",
    )


def _none_entry(sent_at: datetime) -> dict:
    return {
        "ist_date": sent_at.date().isoformat(),
        "sent_at_utc": sent_at.astimezone(timezone.utc).isoformat(),
        "container_restart_count": 0,
        "sent": True,
        "bytes": 540,
        "action_needed": "NONE",
    }


def _nonnone_entry(sent_at: datetime, action: str = "some issue") -> dict:
    entry = _none_entry(sent_at)
    entry["action_needed"] = action
    return entry


# ── 1. Counter excludes digests inside anomaly windows ────────────────────


def test_counter_excludes_digest_in_anomaly_window(cfg: dd.DigestConfig) -> None:
    """Two NONE digests; one falls inside a backfilled anomaly window —
    must be subtracted from the effective counter."""
    day1 = datetime(2026, 5, 23, 12, 46, 32, tzinfo=timezone.utc)
    window = {
        "start": "2026-05-23T13:29:44+00:00",
        "end":   "2026-05-23T15:07:46+00:00",
        "reason": "phantom_ena_crash_loop",
    }
    _write_marker(cfg.data_dir, day1_at=day1, anomaly_windows=[window])
    _write_digest_log(cfg.data_dir, [
        _none_entry(datetime(2026, 5, 23, 13, 0, 0, tzinfo=timezone.utc)),   # pre-window
        _none_entry(datetime(2026, 5, 23, 14, 0, 0, tzinfo=timezone.utc)),   # IN window
        _none_entry(datetime(2026, 5, 23, 16, 0, 0, tzinfo=timezone.utc)),   # post-window
    ])
    marker = dd._read_json(cfg.data_dir / dd.WATCHER_MARKER_FILENAME)
    counter = dd.compute_soak_counter(
        cfg, marker,
        as_of=datetime(2026, 5, 24, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert counter is not None
    assert counter["none_digests_count"] == 3
    assert counter["excluded_digests_count"] == 1
    assert counter["effective_counter"] == 2


# ── 2. Counter resumes after window closes ────────────────────────────────


def test_counter_resumes_after_anomaly_window_closes(cfg: dd.DigestConfig) -> None:
    """Once a window is closed, subsequent NONE digests count again."""
    day1 = datetime(2026, 5, 23, 12, 46, 32, tzinfo=timezone.utc)
    window = {
        "start": "2026-05-23T13:00:00+00:00",
        "end":   "2026-05-23T14:00:00+00:00",
        "reason": "test",
    }
    _write_marker(cfg.data_dir, day1_at=day1, anomaly_windows=[window])
    _write_digest_log(cfg.data_dir, [
        _none_entry(datetime(2026, 5, 23, 13, 30, 0, tzinfo=timezone.utc)),  # excluded
        _none_entry(datetime(2026, 5, 23, 14, 30, 0, tzinfo=timezone.utc)),  # counted
        _none_entry(datetime(2026, 5, 23, 18, 0, 0, tzinfo=timezone.utc)),   # counted
        _none_entry(datetime(2026, 5, 24, 9, 0, 0, tzinfo=timezone.utc)),    # counted
    ])
    counter = dd.compute_soak_counter(
        cfg, dd._read_json(cfg.data_dir / dd.WATCHER_MARKER_FILENAME),
        as_of=datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert counter is not None
    assert counter["effective_counter"] == 3


# ── 3. Marker has anomaly_windows field after backfill ───────────────────


def test_marker_has_anomaly_windows_field(cfg: dd.DigestConfig) -> None:
    """A backfilled marker contains the anomaly_windows list with the
    expected schema (start ISO + end ISO + reason)."""
    day1 = datetime(2026, 5, 23, 12, 46, 32, tzinfo=timezone.utc)
    window = {
        "start": "2026-05-23T13:29:44+00:00",
        "end":   "2026-05-23T15:07:46+00:00",
        "reason": "phantom_ena_crash_loop",
    }
    _write_marker(cfg.data_dir, day1_at=day1, anomaly_windows=[window])

    raw = json.loads(
        (cfg.data_dir / dd.WATCHER_MARKER_FILENAME).read_text(encoding="utf-8")
    )
    assert "anomaly_windows" in raw
    assert isinstance(raw["anomaly_windows"], list)
    assert len(raw["anomaly_windows"]) == 1
    w = raw["anomaly_windows"][0]
    assert {"start", "end", "reason"} <= set(w.keys())
    assert w["reason"] == "phantom_ena_crash_loop"


# ── 4. Open anomaly window closes on next NONE-NONE digest ──────────────


def test_open_anomaly_window_closes_on_next_NONE_digest(cfg: dd.DigestConfig) -> None:
    """enforce_anomaly_window_state should:
       - Open a new window when action != NONE and no open window exists.
       - Close the open window (set end=as_of) on the next NONE digest."""
    day1 = datetime(2026, 5, 23, 12, 46, 32, tzinfo=timezone.utc)
    _write_marker(cfg.data_dir, day1_at=day1, anomaly_windows=[])

    # First call: action != NONE -> opens a window.
    incident_at = datetime(2026, 5, 23, 13, 0, 0, tzinfo=timezone.utc)
    marker = dd._read_json(cfg.data_dir / dd.WATCHER_MARKER_FILENAME)
    updated = dd.enforce_anomaly_window_state(
        cfg, marker, action_needed="reconciler HALTED", as_of=incident_at,
    )
    assert updated is not None
    assert len(updated["anomaly_windows"]) == 1
    assert updated["anomaly_windows"][0]["end"] is None
    assert updated["anomaly_windows"][0]["start"] == incident_at.isoformat()

    # Second call: still not NONE -> no new window opened (one already open).
    still_bad_at = datetime(2026, 5, 23, 13, 15, 0, tzinfo=timezone.utc)
    marker2 = dd._read_json(cfg.data_dir / dd.WATCHER_MARKER_FILENAME)
    updated2 = dd.enforce_anomaly_window_state(
        cfg, marker2, action_needed="reconciler HALTED still", as_of=still_bad_at,
    )
    assert len(updated2["anomaly_windows"]) == 1, "must not open a second window"
    assert updated2["anomaly_windows"][0]["end"] is None

    # Third call: NONE -> closes the window.
    recovered_at = datetime(2026, 5, 23, 15, 7, 46, tzinfo=timezone.utc)
    marker3 = dd._read_json(cfg.data_dir / dd.WATCHER_MARKER_FILENAME)
    updated3 = dd.enforce_anomaly_window_state(
        cfg, marker3, action_needed="NONE", as_of=recovered_at,
    )
    assert updated3["anomaly_windows"][0]["end"] == recovered_at.isoformat()


# ── 5. Multiple anomaly windows compose correctly ──────────────────────


def test_multiple_anomaly_windows_compose_correctly(cfg: dd.DigestConfig) -> None:
    """Two non-overlapping windows; a NONE digest in each must be
    excluded; a NONE digest between them and one after must be counted.
    Demonstrates _in_any_window's logical OR over windows."""
    day1 = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)
    windows = [
        {"start": "2026-05-23T05:00:00+00:00",
         "end":   "2026-05-23T06:00:00+00:00",
         "reason": "first"},
        {"start": "2026-05-23T09:00:00+00:00",
         "end":   "2026-05-23T10:00:00+00:00",
         "reason": "second"},
    ]
    _write_marker(cfg.data_dir, day1_at=day1, anomaly_windows=windows)
    _write_digest_log(cfg.data_dir, [
        _none_entry(datetime(2026, 5, 23, 5, 30, 0, tzinfo=timezone.utc)),   # excluded #1
        _none_entry(datetime(2026, 5, 23, 7, 0, 0, tzinfo=timezone.utc)),    # counted
        _none_entry(datetime(2026, 5, 23, 9, 30, 0, tzinfo=timezone.utc)),   # excluded #2
        _none_entry(datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc)),   # counted
    ])
    counter = dd.compute_soak_counter(
        cfg, dd._read_json(cfg.data_dir / dd.WATCHER_MARKER_FILENAME),
        as_of=datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert counter["none_digests_count"] == 4
    assert counter["excluded_digests_count"] == 2
    assert counter["effective_counter"] == 2


# ── Bonus: open window covers from start onward ──────────────────────────


def test_open_window_covers_from_start_onward(cfg: dd.DigestConfig) -> None:
    """An open window (end=None) excludes all NONE digests after start."""
    day1 = datetime(2026, 5, 23, 0, 0, 0, tzinfo=timezone.utc)
    windows = [
        {"start": "2026-05-23T10:00:00+00:00", "end": None, "reason": "ongoing"},
    ]
    _write_marker(cfg.data_dir, day1_at=day1, anomaly_windows=windows)
    _write_digest_log(cfg.data_dir, [
        _none_entry(datetime(2026, 5, 23, 9, 0, 0, tzinfo=timezone.utc)),  # counted
        _none_entry(datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc)), # excluded
        _none_entry(datetime(2026, 5, 23, 20, 0, 0, tzinfo=timezone.utc)), # excluded
    ])
    counter = dd.compute_soak_counter(
        cfg, dd._read_json(cfg.data_dir / dd.WATCHER_MARKER_FILENAME),
        as_of=datetime(2026, 5, 24, 0, 0, 0, tzinfo=timezone.utc),
    )
    assert counter["effective_counter"] == 1
