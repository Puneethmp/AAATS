"""Tests for D.2 watchdog 24h pager threshold + persistent restart history.

Closes the 2026-05-23 known issue
docs/known_issues/2026-05-23_pager_5plus_restart_not_firing.md: the
operator-away runbook promised pager + auto-HALT_ALL on "5+ container
restarts in one calendar day" but the watchdog had no such code path —
only an in-memory 30-min rolling rate-limit that escalated as
info-level.

Required cases (per session 12 [1] prompt):
  - test_persistent_history_roundtrip
  - test_persistent_history_prunes_past_24h
  - test_daily_threshold_fires_pager_and_halt
  - test_daily_threshold_does_not_fire_below_threshold
  - test_escalation_message_carries_pager_prefix_and_critical_severity
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from health import watchdog as wd


# ── Helpers ───────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point WATCHDOG_STATE_PATH at a tmp file so tests don't pollute
    /app/data/watchdog_state.json."""
    state_path = tmp_path / "watchdog_state.json"
    monkeypatch.setattr(wd, "WATCHDOG_STATE_PATH", state_path)
    return state_path


# ── 1. Persistent history round-trip ─────────────────────────────────────


def test_persistent_history_roundtrip(isolated_state: Path) -> None:
    now = time.time()
    history = [now - 3600 * i for i in range(7)]   # 7 entries, each 1h apart, all within 24h
    wd._save_persistent_restart_history(history)

    reloaded = wd._load_persistent_restart_history(now_ts=now)
    assert len(reloaded) == 7
    assert all(now - 24 * 3600 <= t <= now for t in reloaded)


# ── 2. Pruning drops entries older than 24h ──────────────────────────────


def test_persistent_history_prunes_past_24h(isolated_state: Path) -> None:
    now = time.time()
    # 3 recent + 3 too-old entries persisted on disk.
    history = [now - 1, now - 3600, now - 10 * 3600,
               now - (24 * 3600 + 60),    # 1 min past TTL
               now - (48 * 3600),          # 2 days old
               now - (72 * 3600)]          # 3 days old
    wd._save_persistent_restart_history(history)

    reloaded = wd._load_persistent_restart_history(now_ts=now)
    assert len(reloaded) == 3, f"expected 3 entries within 24h; got {reloaded}"
    for ts in reloaded:
        assert now - ts <= 24 * 3600


# ── 3. Daily threshold fires pager + halt ────────────────────────────────


def test_daily_threshold_fires_pager_and_halt(isolated_state: Path) -> None:
    sent: list[tuple[Any, ...]] = []
    halted: list[tuple[Any, ...]] = []

    def fake_send(*args: Any, **kwargs: Any) -> None:
        sent.append((args, kwargs))

    class FakeKillSwitch:
        @staticmethod
        def halt(market: str, reason: str, triggered_by: str) -> None:
            halted.append((market, reason, triggered_by))

    history = [time.time() - i for i in range(5)]   # 5 restarts within last few seconds

    with patch("observability.alerts.send_alert", fake_send), \
         patch.dict("sys.modules", {"foundation": __import__("types").ModuleType("foundation")}):
        # Inject our fake kill_switch into the foundation module.
        import sys as _sys
        _sys.modules["foundation"].kill_switch = FakeKillSwitch  # type: ignore[attr-defined]

        fired = wd._check_daily_pager_threshold(history)

    assert fired is True
    assert len(sent) == 1, f"expected exactly one pager alert; got {sent}"
    args, kwargs = sent[0]
    msg = args[0] if args else kwargs.get("text", "")
    assert "[PAGER]" in msg, f"alert must carry [PAGER] prefix; got: {msg!r}"
    assert "5 restarts" in msg, msg
    assert kwargs.get("severity") == "critical"

    assert len(halted) == 1
    assert halted[0][0] == "crypto"
    assert "5 restarts in 24h" in halted[0][1]
    assert halted[0][2] == "watchdog_daily_threshold"


# ── 4. Below threshold: no pager, no halt ─────────────────────────────────


def test_daily_threshold_does_not_fire_below_threshold(isolated_state: Path) -> None:
    sent: list[tuple[Any, ...]] = []
    halted: list[tuple[Any, ...]] = []

    history = [time.time() - i for i in range(4)]   # only 4 restarts, threshold is 5

    with patch("observability.alerts.send_alert",
               lambda *a, **kw: sent.append((a, kw))):
        fired = wd._check_daily_pager_threshold(history)

    assert fired is False
    assert sent == []
    assert halted == []


# ── 5. Escalation message carries [PAGER] + critical ─────────────────────


def test_escalation_message_carries_pager_prefix_and_critical_severity(
    isolated_state: Path, tmp_path: Path,
) -> None:
    """When the watchdog tick() enters the escalate branch (rate-limit
    hit inside the 30-min window), the alert must be [PAGER] + critical.

    Pre-2026-05-23 fix this was info-level only, which is why the live
    crash loop produced no operator-phone pager."""
    sent: list[tuple[Any, ...]] = []

    def fake_send(*args: Any, **kwargs: Any) -> None:
        sent.append((args, kwargs))

    # Build a Watchdog whose state is already at the rate limit.
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(
        json.dumps({
            "timestamp": "2026-05-23T13:00:00+00:00",
            "cycle": 1, "market": "crypto",
        }),
        encoding="utf-8",
    )
    state = wd.WatchdogState(rate_limit_max=3, rate_limit_window_sec=1800)
    now = time.time()
    for i in range(3):
        state.record_restart(now - 60 * i)   # 3 restarts in the last 3 minutes

    watchdog = wd.Watchdog(heartbeat_path=heartbeat, state=state)
    # Make the heartbeat stale relative to "now" so classify returns escalate.
    with patch("health.watchdog._read_heartbeat_ts", return_value=now - 100_000), \
         patch("health.watchdog._send_alert", fake_send), \
         patch("health.watchdog._restart_container", return_value=True):
        verb = watchdog.tick(now_ts=now)

    assert verb == "escalate"
    # Find the escalation alert (the one carrying ESCALATION text).
    escalation_calls = [
        c for c in sent
        if (c[0] and "ESCALATION" in str(c[0][0]))
    ]
    assert escalation_calls, f"escalation alert was not emitted; got {sent}"
    args, kwargs = escalation_calls[0]
    msg = args[0]
    assert "[PAGER]" in msg, f"escalation must carry [PAGER] prefix; got: {msg!r}"
    assert kwargs.get("severity") == "critical", (
        f"escalation must have severity='critical'; got: {kwargs!r}"
    )
