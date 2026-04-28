"""
Tests for foundation/kill_switch.py.
Verifies per-market halt flags, persistence, isolation between markets, and audit trail writes.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolated_halt_file(tmp_path, monkeypatch):
    """Each test gets its own halt state file — no cross-test contamination."""
    monkeypatch.setattr("foundation.kill_switch.HALT_FILE", tmp_path / "halt_state.json")


def _halt(market, reason="test reason", triggered_by="pytest"):
    """Helper: call halt() with mocked audit trail and alerts."""
    with (
        patch("foundation.kill_switch.AuditTrail") as MockAudit,
        patch("foundation.kill_switch.send_alert"),
    ):
        from foundation.kill_switch import halt

        halt(market=market, reason=reason, triggered_by=triggered_by)
        return MockAudit


class TestHalt:
    def test_halt_us_sets_us_flag(self):
        from foundation.kill_switch import is_halted

        _halt("us")
        assert is_halted("us") is True

    def test_halt_india_sets_india_flag(self):
        from foundation.kill_switch import is_halted

        _halt("india")
        assert is_halted("india") is True

    def test_halt_crypto_sets_crypto_flag(self):
        from foundation.kill_switch import is_halted

        _halt("crypto")
        assert is_halted("crypto") is True

    def test_halt_india_does_not_affect_us(self):
        from foundation.kill_switch import is_halted

        _halt("india")
        assert is_halted("us") is False

    def test_halt_us_does_not_affect_india(self):
        from foundation.kill_switch import is_halted

        _halt("us")
        assert is_halted("india") is False

    def test_halt_all_sets_every_market(self):
        from foundation.kill_switch import is_halted

        _halt("all")
        assert is_halted("us") is True
        assert is_halted("india") is True
        assert is_halted("crypto") is True

    def test_halt_writes_to_audit_trail(self):
        mock_audit_cls = _halt("us", reason="Drawdown limit hit", triggered_by="drawdown_guardian")
        instance = mock_audit_cls.return_value
        instance.append.assert_called_once()
        kwargs = instance.append.call_args.kwargs
        assert kwargs["event_type"] == "HALT"
        assert kwargs["result"] == "HALTED"
        assert "drawdown_guardian" in str(kwargs["details"])

    def test_halt_sends_telegram_alert(self):
        with (
            patch("foundation.kill_switch.AuditTrail"),
            patch("foundation.kill_switch.send_alert") as mock_alert,
        ):
            from foundation.kill_switch import halt

            halt(market="us", reason="Test", triggered_by="test")
            mock_alert.assert_called_once()
            call_args = mock_alert.call_args
            assert "US" in call_args[0][0] or "us" in str(call_args)

    def test_halt_alert_failure_does_not_prevent_halt(self, monkeypatch):
        """Even if Telegram fails, the halt must still be applied."""
        from foundation.kill_switch import is_halted

        with (
            patch("foundation.kill_switch.AuditTrail"),
            patch("foundation.kill_switch.send_alert", side_effect=Exception("telegram down")),
        ):
            from foundation.kill_switch import halt

            halt(market="us", reason="Test resilience", triggered_by="test")

        assert is_halted("us") is True


class TestPersistence:
    def test_halt_state_written_to_json(self, tmp_path, monkeypatch):
        halt_file = tmp_path / "halt_state.json"
        monkeypatch.setattr("foundation.kill_switch.HALT_FILE", halt_file)

        _halt("crypto")

        assert halt_file.exists()
        state = json.loads(halt_file.read_text())
        assert state["crypto"] is True

    def test_is_halted_reads_from_disk(self, tmp_path, monkeypatch):
        """is_halted must reflect disk state, not in-memory state."""
        halt_file = tmp_path / "halt_state.json"
        monkeypatch.setattr("foundation.kill_switch.HALT_FILE", halt_file)

        # Write state directly to disk, bypassing halt()
        halt_file.write_text(json.dumps({"us": True, "india": False, "crypto": False}))

        from foundation.kill_switch import is_halted

        assert is_halted("us") is True
        assert is_halted("india") is False


class TestReset:
    def test_reset_clears_halt_flag(self):
        from foundation.kill_switch import is_halted, reset

        _halt("us")
        assert is_halted("us") is True

        with (
            patch("foundation.kill_switch.AuditTrail"),
            patch("foundation.kill_switch.send_alert"),
        ):
            reset(market="us", authorized_by="Puneeth", reason="Issue resolved")

        assert is_halted("us") is False

    def test_reset_all_clears_every_market(self):
        from foundation.kill_switch import is_halted, reset

        _halt("all")

        with (
            patch("foundation.kill_switch.AuditTrail"),
            patch("foundation.kill_switch.send_alert"),
        ):
            reset(market="all", authorized_by="Puneeth", reason="Full system review complete")

        assert is_halted("us") is False
        assert is_halted("india") is False
        assert is_halted("crypto") is False

    def test_reset_writes_to_audit_trail(self):
        _halt("india")

        with (
            patch("foundation.kill_switch.AuditTrail") as MockAudit,
            patch("foundation.kill_switch.send_alert"),
        ):
            from foundation.kill_switch import reset

            reset(market="india", authorized_by="Puneeth", reason="Fixed")
            instance = MockAudit.return_value
            instance.append.assert_called_once()
            kwargs = instance.append.call_args.kwargs
            assert kwargs["result"] == "GO"
            assert "RESET" in str(kwargs["details"])

    def test_reset_does_not_affect_other_markets(self):
        from foundation.kill_switch import is_halted, reset

        _halt("all")

        with (
            patch("foundation.kill_switch.AuditTrail"),
            patch("foundation.kill_switch.send_alert"),
        ):
            reset(market="us", authorized_by="Puneeth", reason="US fixed")

        assert is_halted("us") is False
        assert is_halted("india") is True  # untouched
        assert is_halted("crypto") is True  # untouched
