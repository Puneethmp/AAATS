"""Tests for scripts/reset_paper_book_200.py.

Six required cases per the session 10/11 prompt:
  - test_refuses_on_NO_GO
  - test_proceeds_on_GO
  - test_proceeds_on_PARTIAL_with_watcher_note
  - test_seeds_200_baseline
  - test_writes_d5_day1_marker
  - test_rollback_on_no_NONE_digest_in_window

The reset script's pure-logic helpers are testable directly. The
orchestration loop is tested with a stub BoxIO that records every
command + content sent and lets the test script-feed digest responses
back.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from scripts import reset_paper_book_200 as reset


# ── Backtest gate ─────────────────────────────────────────────────────────


def _write_summary(tmp_path: Path, recommendation: str) -> Path:
    path = tmp_path / "c3_60d_summary.json"
    path.write_text(
        json.dumps({"recommendation": recommendation, "pnl_usd": 1.0}),
        encoding="utf-8",
    )
    return path


def test_refuses_on_NO_GO(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                          capsys: pytest.CaptureFixture[str]) -> None:
    """NO-GO verdict -> main() exits non-zero, prints a loud refusal,
    and does NOT attempt box ops."""
    summary = _write_summary(tmp_path, "NO_GO")
    monkeypatch.setattr(reset, "BACKTEST_SUMMARY", summary)

    rc = reset.main(["--apply"])
    assert rc == 1, f"expected exit 1 on NO-GO, got {rc}"

    captured = capsys.readouterr().out
    assert "NO-GO" in captured.upper()
    assert "refus" in captured.lower(), "must visibly refuse, not silently exit"


def test_proceeds_on_GO(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                       capsys: pytest.CaptureFixture[str]) -> None:
    """GO verdict in --dry-run -> exit 0, prints the GO message + plan."""
    summary = _write_summary(tmp_path, "GO")
    monkeypatch.setattr(reset, "BACKTEST_SUMMARY", summary)

    rc = reset.main(["--dry-run"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "GO backtest verdict" in captured
    assert "DRY-RUN" in captured.upper()


def test_proceeds_on_PARTIAL_with_watcher_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """PARTIAL verdict -> exit 0 AND a divergence-watcher note must
    appear in the printed plan."""
    summary = _write_summary(tmp_path, "PARTIAL")
    monkeypatch.setattr(reset, "BACKTEST_SUMMARY", summary)

    rc = reset.main(["--dry-run"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "PARTIAL" in captured
    assert "divergence-watcher" in captured.lower()
    assert "C3" in captured
    # Threshold band must be surfaced in the note so a reading operator
    # sees what would auto-halt.
    assert "$-2.00" in captured and "$+2.00" in captured


# ── Seed payload ──────────────────────────────────────────────────────────


def test_seeds_200_baseline() -> None:
    """seed_state_payload($200) returns the canonical paper_portfolio.json
    payload at the doctrine-amended floor with all counters zeroed."""
    payload = reset.seed_state_payload(200.0)
    assert payload["crypto"]["capital"] == 200.0
    assert payload["crypto"]["starting_equity"] == 200.0
    assert payload["crypto"]["realized_pnl"] == 0.0
    assert payload["crypto"]["total_trades"] == 0
    assert payload["crypto"]["wins"] == 0
    assert payload["crypto"]["losses"] == 0
    assert payload["crypto"]["settlement_queue"] == []


# ── Day-1 marker ──────────────────────────────────────────────────────────


def test_writes_d5_day1_marker() -> None:
    """build_day1_marker returns the contracted marker schema."""
    day1 = _dt.datetime(2026, 5, 25, 12, 30, 0, tzinfo=_dt.timezone.utc)
    marker = reset.build_day1_marker(day1)
    assert marker["day1_at"] == "2026-05-25T12:30:00+00:00"
    assert marker["starting_equity_usd"] == 200.0
    assert marker["divergence_watcher_armed"] is True
    assert marker["watcher_window_days"] == 7
    assert marker["c3_threshold_low_usd"] == -2.0
    assert marker["c3_threshold_high_usd"] == 2.0


# ── Rollback on no-NONE-in-window ─────────────────────────────────────────


class _StubBox:
    """Records every command + file write so tests can assert ordering
    and content. The digest_responses queue script-feeds digest outputs."""

    def __init__(self, digest_responses: list[str] | None = None) -> None:
        self.commands: list[tuple[str, str]] = []
        self.files: dict[str, str] = {}
        self._digests = list(digest_responses or [])

    def run(self, cmd: str, label: str, timeout: int = 60) -> tuple[int, str]:
        self.commands.append((label, cmd))
        if "daily_digest" in cmd and "--dry-run" in cmd:
            if self._digests:
                return 0, self._digests.pop(0)
            return 0, "Action needed: container starting"
        return 0, "OK"

    def write_text(self, remote_path: str, content: str, label: str) -> None:
        self.files[remote_path] = content


def test_rollback_on_no_NONE_digest_in_window() -> None:
    """If every digest poll returns non-NONE, the orchestrator must:
       - return exit_code 2
       - write a failure marker (failed_at + reason) to the marker path
       - re-engage the operator kill switch on crypto"""
    # Every poll returns a non-NONE action.
    box = _StubBox(digest_responses=["Action needed: container starting"] * 50)

    seed_payload = reset.seed_state_payload(200.0)

    sleep_calls: list[float] = []
    now_calls: list[int] = [0]

    def fake_sleep(sec: float) -> None:
        sleep_calls.append(sec)

    base_time = _dt.datetime(2026, 5, 25, 12, 0, 0, tzinfo=_dt.timezone.utc)

    def fake_now() -> _dt.datetime:
        now_calls[0] += 1
        return base_time + _dt.timedelta(seconds=now_calls[0])

    exit_code, marker = reset.execute_reset(
        box,
        remote_dir="/home/aaats/aaats",
        seed_payload=seed_payload,
        now_fn=fake_now,
        poll_interval_sec=30,
        poll_window_sec=120,  # 4 polls then rollback
        sleep_fn=fake_sleep,
    )

    assert exit_code == 2, f"expected rollback exit 2, got {exit_code}"
    assert "failed_at" in marker
    assert "day1_at" not in marker
    assert marker["divergence_watcher_armed"] is False
    assert "did not reach Action needed: NONE" in marker["reason"]

    # Marker file written to the canonical path.
    assert "/home/aaats/aaats/data/d5_day1_marker.json" in box.files
    marker_on_box = json.loads(
        box.files["/home/aaats/aaats/data/d5_day1_marker.json"]
    )
    assert "failed_at" in marker_on_box

    # Operator kill re-engaged on rollback.
    halt_commands = [
        c for label, c in box.commands
        if "kill_switch.halt('crypto'" in c
    ]
    assert halt_commands, (
        f"rollback must call kill_switch.halt on crypto; commands={box.commands}"
    )


def test_success_when_digest_eventually_reaches_NONE() -> None:
    """Bonus regression coverage of the happy path: 2 non-NONE polls
    followed by a NONE poll writes the day-1 marker and returns exit 0.
    Belongs in this file because it exercises the same orchestrator the
    rollback test does."""
    box = _StubBox(digest_responses=[
        "Action needed: container starting",
        "Action needed: container starting",
        # Realistic digest body — the parser only needs the action line.
        "AAATS daily digest -- 2026-05-25\n\nAction needed: NONE\n",
    ])
    seed_payload = reset.seed_state_payload(200.0)

    base = _dt.datetime(2026, 5, 25, 12, 0, 0, tzinfo=_dt.timezone.utc)
    now_iter = iter([base + _dt.timedelta(seconds=i) for i in range(50)])

    exit_code, marker = reset.execute_reset(
        box,
        remote_dir="/home/aaats/aaats",
        seed_payload=seed_payload,
        now_fn=lambda: next(now_iter),
        poll_interval_sec=30,
        poll_window_sec=600,
        sleep_fn=lambda _s: None,
    )

    assert exit_code == 0
    assert "day1_at" in marker
    assert marker["starting_equity_usd"] == 200.0
    assert marker["divergence_watcher_armed"] is True
