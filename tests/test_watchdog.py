"""Tests for the D.2 heartbeat watchdog (health/watchdog.py)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


# --- State machine: pure logic, IO-free -------------------------------------


class TestWatchdogStateClassify:
    def test_fresh_heartbeat_is_ok(self):
        from health.watchdog import WatchdogState
        s = WatchdogState(stale_threshold_sec=2700)
        # heartbeat 60s old → fresh.
        assert s.classify(heartbeat_ts=1_000_000.0, now_ts=1_000_060.0) == "ok"

    def test_stale_heartbeat_triggers_restart(self):
        from health.watchdog import WatchdogState
        s = WatchdogState(stale_threshold_sec=2700)
        # heartbeat 3000s old (> 2700s threshold) → restart.
        assert s.classify(heartbeat_ts=1_000_000.0, now_ts=1_003_000.0) == "restart"

    def test_missing_heartbeat_treated_as_restart(self):
        from health.watchdog import WatchdogState
        s = WatchdogState(stale_threshold_sec=2700)
        # No file / unreadable → restart_missing (still a restart action).
        assert s.classify(heartbeat_ts=None, now_ts=1_000_000.0) == "restart_missing"

    def test_rate_limit_exhausted_escalates(self):
        from health.watchdog import WatchdogState
        s = WatchdogState(stale_threshold_sec=2700, rate_limit_max=3,
                          rate_limit_window_sec=1800)
        # 3 restarts within the last 30 minutes — 4th detection escalates.
        now = 1_000_000.0
        for delta in (-1500, -1000, -500):
            s.record_restart(now + delta)
        assert s.classify(heartbeat_ts=now - 3000, now_ts=now) == "escalate"

    def test_old_restarts_drop_out_of_window(self):
        from health.watchdog import WatchdogState
        s = WatchdogState(stale_threshold_sec=2700, rate_limit_max=3,
                          rate_limit_window_sec=1800)
        # 3 restarts but they're outside the 30-min window → not rate-limited.
        now = 1_000_000.0
        for delta in (-5000, -4500, -4000):
            s.record_restart(now + delta)
        # Should restart, not escalate.
        assert s.classify(heartbeat_ts=now - 3000, now_ts=now) == "restart"
        assert s.restart_count_in_window(now) == 0

    def test_record_restart_advances_window_count(self):
        from health.watchdog import WatchdogState
        s = WatchdogState(rate_limit_window_sec=1800)
        now = 1_000_000.0
        assert s.restart_count_in_window(now) == 0
        s.record_restart(now)
        assert s.restart_count_in_window(now) == 1


# --- IO shell with mocked docker + Telegram --------------------------------


@pytest.fixture()
def tmp_heartbeat(tmp_path) -> Path:
    """Build a tmp_path/data/heartbeat.json with controllable timestamps."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir / "heartbeat.json"


def _write_heartbeat(
    path: Path, *, age_seconds: float, market: str = "crypto",
    base_ts: float | None = None,
) -> None:
    """Write a heartbeat ``age_seconds`` old relative to ``base_ts`` (default: real now)."""
    import time
    base = time.time() if base_ts is None else base_ts
    ts = datetime.fromtimestamp(base - age_seconds, tz=timezone.utc)
    path.write_text(json.dumps({
        "timestamp": ts.isoformat(),
        "cycle": 47,
        "market": market,
        "cycle_duration_seconds": 12.0,
    }), encoding="utf-8")


class TestWatchdogTickIntegration:
    def test_fresh_heartbeat_no_action(self, tmp_heartbeat, monkeypatch):
        import health.watchdog as wd

        called = {"restart": 0, "alert": 0}
        monkeypatch.setattr(wd, "_restart_container",
                            lambda c: called.__setitem__("restart", called["restart"] + 1) or True)
        monkeypatch.setattr(wd, "_send_alert",
                            lambda m: called.__setitem__("alert", called["alert"] + 1))

        _write_heartbeat(tmp_heartbeat, age_seconds=60)
        watchdog = wd.Watchdog(heartbeat_path=tmp_heartbeat)
        verb = watchdog.tick()

        assert verb == "ok"
        assert called["restart"] == 0
        assert called["alert"] == 0

    def test_stale_heartbeat_calls_docker_restart_and_alerts(self, tmp_heartbeat, monkeypatch):
        import health.watchdog as wd

        called = {"restart": 0, "alerts": []}
        monkeypatch.setattr(wd, "_restart_container",
                            lambda c: called.__setitem__("restart", called["restart"] + 1) or True)
        monkeypatch.setattr(wd, "_send_alert",
                            lambda m: called["alerts"].append(m))

        # 60min old > 45min threshold (3 × 15min cycle).
        _write_heartbeat(tmp_heartbeat, age_seconds=3600)
        watchdog = wd.Watchdog(heartbeat_path=tmp_heartbeat)
        verb = watchdog.tick()

        assert verb == "restart"
        assert called["restart"] == 1
        assert any("restarting" in m for m in called["alerts"])

    def test_four_consecutive_stale_ticks_escalate_on_fourth(self, tmp_heartbeat, monkeypatch):
        import health.watchdog as wd

        called = {"restart": 0, "alerts": []}
        monkeypatch.setattr(wd, "_restart_container",
                            lambda c: called.__setitem__("restart", called["restart"] + 1) or True)
        monkeypatch.setattr(wd, "_send_alert",
                            lambda m: called["alerts"].append(m))

        # Heartbeat timestamped 1h before the synthetic `now`.
        now = 1_000_000.0
        _write_heartbeat(tmp_heartbeat, age_seconds=3600, base_ts=now)
        watchdog = wd.Watchdog(heartbeat_path=tmp_heartbeat)

        # 3 restarts within the same instant, then a 4th stale tick.
        for i in range(3):
            v = watchdog.tick(now_ts=now + i)
            assert v == "restart", f"tick {i} expected restart, got {v}"
        v = watchdog.tick(now_ts=now + 4)
        assert v == "escalate"
        assert called["restart"] == 3
        assert any("ESCALATION" in m for m in called["alerts"])

    def test_missing_heartbeat_file_restarts(self, tmp_heartbeat, monkeypatch):
        import health.watchdog as wd

        called = {"restart": 0, "alerts": []}
        monkeypatch.setattr(wd, "_restart_container",
                            lambda c: called.__setitem__("restart", called["restart"] + 1) or True)
        monkeypatch.setattr(wd, "_send_alert",
                            lambda m: called["alerts"].append(m))

        # No file at all (don't create it).
        watchdog = wd.Watchdog(heartbeat_path=tmp_heartbeat)
        verb = watchdog.tick()

        assert verb == "restart_missing"
        assert called["restart"] == 1

    def test_docker_restart_failure_emits_followup_alert(self, tmp_heartbeat, monkeypatch):
        import health.watchdog as wd

        called = {"alerts": []}
        monkeypatch.setattr(wd, "_restart_container", lambda c: False)
        monkeypatch.setattr(wd, "_send_alert", lambda m: called["alerts"].append(m))

        _write_heartbeat(tmp_heartbeat, age_seconds=3600)
        watchdog = wd.Watchdog(heartbeat_path=tmp_heartbeat)
        watchdog.tick()

        assert any("FAILED" in m for m in called["alerts"])
