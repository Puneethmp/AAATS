"""
Tests for the alerts-log writer in observability/alerts.py.

The writer is a side-effect of send_alert(); it must:
  - Append atomically (tmp+replace) so a SIGINT mid-write either leaves the
    old file intact or fully replaces it.
  - Treat the log as a JSON list; create on first append; gracefully recover
    from a corrupt file (treat as empty).
  - Stamp each row with ts, market, severity, message, correlation_id.
  - Auto-generate a UUID4 correlation_id if the caller didn't supply one.
  - Infer severity from message body when not explicitly provided.
  - Never raise — alert-log loss is preferable to blocking the trading loop.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_alerts_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point AAATS_DATA to a tmp dir so each test gets its own alerts_log.json."""
    monkeypatch.setenv("AAATS_DATA", str(tmp_path))
    # Strip Telegram credentials so the inner asyncio path is a no-op.
    for key in (
        "ALERTS__TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "ALERTS__TELEGRAM_CHAT_ID",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    return tmp_path / "alerts_log.json"


def _read_log(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_first_send_creates_log_with_one_row(_isolated_alerts_log: Path) -> None:
    from observability.alerts import send_alert

    cid = send_alert("Test alert body", market="crypto")
    rows = _read_log(_isolated_alerts_log)
    assert len(rows) == 1
    assert rows[0]["market"] == "crypto"
    assert rows[0]["message"] == "Test alert body"
    assert rows[0]["correlation_id"] == cid
    # Default severity from a vanilla body is "info".
    assert rows[0]["severity"] == "info"
    # ts is UTC ISO 8601-ish.
    assert "T" in rows[0]["ts"]


def test_repeated_sends_append(_isolated_alerts_log: Path) -> None:
    from observability.alerts import send_alert

    send_alert("first", market="crypto")
    send_alert("second", market="crypto")
    send_alert("third", market="us")
    rows = _read_log(_isolated_alerts_log)
    assert [r["message"] for r in rows] == ["first", "second", "third"]
    assert [r["market"] for r in rows] == ["crypto", "crypto", "us"]


def test_severity_inferred_from_message_body(_isolated_alerts_log: Path) -> None:
    from observability.alerts import send_alert

    send_alert("⚠️ Recoverable warning here", market="crypto")
    send_alert("🛑 HALT CRYPTO — drawdown breach", market="crypto")
    send_alert("Just an info line", market="system")
    rows = _read_log(_isolated_alerts_log)
    assert rows[0]["severity"] == "warn"
    assert rows[1]["severity"] == "critical"
    assert rows[2]["severity"] == "info"


def test_explicit_severity_overrides_inference(_isolated_alerts_log: Path) -> None:
    from observability.alerts import send_alert

    send_alert("HALT body", market="crypto", severity="info")
    rows = _read_log(_isolated_alerts_log)
    assert rows[0]["severity"] == "info"


def test_explicit_correlation_id_round_trips(_isolated_alerts_log: Path) -> None:
    from observability.alerts import send_alert

    cid = "test-correlation-id-1234"
    returned = send_alert("Body", market="crypto", correlation_id=cid)
    assert returned == cid
    rows = _read_log(_isolated_alerts_log)
    assert rows[0]["correlation_id"] == cid


def test_auto_correlation_id_is_uuid4(_isolated_alerts_log: Path) -> None:
    from observability.alerts import send_alert

    cid = send_alert("Body", market="crypto")
    # Will raise if not a parsable UUID.
    parsed = uuid.UUID(cid)
    assert parsed.version == 4


def test_corrupt_log_is_recovered_as_empty(
    _isolated_alerts_log: Path, tmp_path: Path
) -> None:
    """If the existing log is unparseable, the writer treats it as empty
    and starts fresh; it must not raise."""
    _isolated_alerts_log.write_text("{not-valid-json", encoding="utf-8")

    from observability.alerts import send_alert
    send_alert("after corrupt", market="crypto")
    rows = _read_log(_isolated_alerts_log)
    assert len(rows) == 1
    assert rows[0]["message"] == "after corrupt"


def test_non_list_log_is_recovered_as_empty(_isolated_alerts_log: Path) -> None:
    """A legitimate JSON file that is NOT a list (e.g., a dict) is treated
    as empty — we never crash a caller because the log shape drifted."""
    _isolated_alerts_log.write_text('{"unexpected": "shape"}', encoding="utf-8")

    from observability.alerts import send_alert
    send_alert("after wrong shape", market="crypto")
    rows = _read_log(_isolated_alerts_log)
    assert len(rows) == 1


def test_atomic_write_uses_tmp_then_replace(
    _isolated_alerts_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirms the writer goes through .tmp + os.replace. If the temp
    write succeeds but replace is interrupted, the original file remains
    intact. Here we just verify the .tmp file is gone after a successful
    write (i.e. os.replace actually renamed it)."""
    from observability.alerts import send_alert
    send_alert("first", market="crypto")
    send_alert("second", market="crypto")
    tmp_path_str = str(_isolated_alerts_log) + ".tmp"
    assert not os.path.exists(tmp_path_str), (
        "tmp file left behind — os.replace likely did not run"
    )


def test_signal_interrupted_replace_leaves_old_file_intact(
    _isolated_alerts_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If os.replace raises (OSError, e.g. EINTR from a SIGINT-interrupted
    syscall, or EBUSY/EPERM from a filesystem hiccup), the pre-existing
    log must be untouched and the caller must not raise.

    Note: we use OSError, not KeyboardInterrupt — a Python-level Ctrl+C
    SHOULD propagate through send_alert so the trading loop can shut down
    cleanly. The contract here is "best-effort file IO, never block the
    trading loop on IO failures."
    """
    from observability import alerts

    # First, seed a valid log.
    alerts.send_alert("first", market="crypto")
    snapshot = _isolated_alerts_log.read_text(encoding="utf-8")

    def _boom(_src, _dst):  # noqa: ANN001
        raise OSError(4, "Interrupted system call")  # EINTR

    with patch("observability.alerts.os.replace", _boom):
        # send_alert must not propagate the IO failure.
        try:
            alerts.send_alert("second", market="crypto")
        except Exception:  # noqa: BLE001
            pytest.fail("send_alert propagated an exception from the writer")

    # The pre-existing log must be byte-identical.
    assert _isolated_alerts_log.read_text(encoding="utf-8") == snapshot


def test_keyboard_interrupt_is_not_swallowed(
    _isolated_alerts_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine Ctrl+C (KeyboardInterrupt) must propagate through
    send_alert so the operator can stop the bot. Swallowing BaseException
    would trap shutdown signals."""
    from observability import alerts

    def _kbi(_src, _dst):  # noqa: ANN001
        raise KeyboardInterrupt("operator pressed Ctrl+C")

    with patch("observability.alerts.os.replace", _kbi), pytest.raises(KeyboardInterrupt):
        alerts.send_alert("body", market="crypto")


def test_telegram_not_configured_still_writes_log(
    _isolated_alerts_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even without Telegram creds (paper-mode default), the alerts log is
    still updated. The autouse fixture already strips creds; this assertion
    documents the contract."""
    from observability.alerts import send_alert
    send_alert("paper-mode body", market="crypto")
    rows = _read_log(_isolated_alerts_log)
    assert len(rows) == 1
