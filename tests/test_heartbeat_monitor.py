"""Tests for the FLAT-schema heartbeat reader (post-2026-05-22 cleanup).

The legacy nested writer (``HeartbeatMonitor.emit_heartbeat``) was removed;
the canonical writer is the runner's direct write at
``trading/live_paper_runner.py:1899-1904``. These tests pin the reader to
that flat shape.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# --- helpers ----------------------------------------------------------------


def _write_flat(data_dir: Path, *, market: str, age_seconds: float, cycle: int = 71) -> None:
    """Write the canonical flat heartbeat shape to data_dir/heartbeat.json."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    payload = {
        "timestamp": ts.isoformat(),
        "cycle": cycle,
        "market": market,
        "cycle_duration_seconds": 12.0,
    }
    (data_dir / "heartbeat.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_legacy_nested(data_dir: Path, *, market: str = "crypto") -> None:
    """Write the legacy nested shape (must NOT load through the new reader)."""
    ts = datetime.now(timezone.utc).isoformat()
    payload = {
        market: {
            "timestamp": ts,
            "market": market,
            "status": "RUNNING",
            "cycle_count": 71,
            "error": "",
        }
    }
    (data_dir / "heartbeat.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def monitor(tmp_path):
    """Rebind the module singleton to a fresh tmp data dir."""
    from monitoring import heartbeat_monitor as hm

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    fresh = hm.HeartbeatMonitor(data_dir=str(data_dir))
    return fresh, data_dir


# --- round-trip on the flat shape ------------------------------------------


class TestFlatRoundTrip:
    def test_get_heartbeat_returns_flat_record(self, monitor):
        hm, data_dir = monitor
        _write_flat(data_dir, market="crypto", age_seconds=10)
        hb = hm.get_heartbeat("crypto")
        assert hb is not None
        assert hb.market == "crypto"
        assert hb.cycle == 71
        assert hb.cycle_duration_seconds == 12.0
        # Must NOT have the legacy fields — schema drift sentinels.
        assert not hasattr(hb, "status")
        assert not hasattr(hb, "cycle_count")

    def test_get_all_heartbeats_keys_by_market_field(self, monitor):
        hm, data_dir = monitor
        _write_flat(data_dir, market="crypto", age_seconds=10)
        all_hb = hm.get_all_heartbeats()
        assert set(all_hb.keys()) == {"crypto"}
        assert all_hb["crypto"].market == "crypto"

    def test_is_alive_true_within_max_age(self, monitor):
        hm, data_dir = monitor
        _write_flat(data_dir, market="crypto", age_seconds=10)
        assert hm.is_alive("crypto", max_age_seconds=120) is True

    def test_is_alive_false_when_stale(self, monitor):
        hm, data_dir = monitor
        _write_flat(data_dir, market="crypto", age_seconds=4 * 3600)
        assert hm.is_alive("crypto", max_age_seconds=120) is False


# --- legacy shape is no longer accepted -------------------------------------


class TestLegacyNestedRejected:
    """The nested per-market shape is the bug from catalog row 1 — it must
    fail cleanly (return None / empty dict / False), NOT raise."""

    def test_get_heartbeat_returns_none_on_nested(self, monitor):
        hm, data_dir = monitor
        _write_legacy_nested(data_dir, market="crypto")
        # 'market' key is present but value is a dict, not the market string.
        # _from_raw extracts market=str(dict) which won't equal "crypto" or
        # the conversion will fail — either way, callers see None.
        hb = hm.get_heartbeat("crypto")
        assert hb is None or hb.market != "crypto"

    def test_get_all_heartbeats_does_not_crash_on_nested(self, monitor):
        """Catalog row 1 surfaced as 'argument after ** must be a mapping, not str'.
        The new reader must never raise — empty dict is the contract."""
        hm, data_dir = monitor
        _write_legacy_nested(data_dir, market="crypto")
        # Must return empty dict (or a single bogus entry); MUST NOT raise.
        result = hm.get_all_heartbeats()
        assert isinstance(result, dict)
        assert "crypto" not in result  # legacy nested no longer indexed by market

    def test_is_alive_false_on_nested(self, monitor):
        hm, data_dir = monitor
        _write_legacy_nested(data_dir, market="crypto")
        assert hm.is_alive("crypto", max_age_seconds=120) is False


# --- edge cases ------------------------------------------------------------


class TestEdgeCases:
    def test_missing_file_returns_none(self, monitor):
        hm, _ = monitor
        assert hm.get_heartbeat("crypto") is None
        assert hm.get_all_heartbeats() == {}
        assert hm.is_alive("crypto") is False

    def test_corrupt_json_returns_none(self, monitor):
        hm, data_dir = monitor
        (data_dir / "heartbeat.json").write_text("not-json{", encoding="utf-8")
        assert hm.get_heartbeat("crypto") is None
        assert hm.get_all_heartbeats() == {}
        assert hm.is_alive("crypto") is False

    def test_market_mismatch_returns_none(self, monitor):
        """Heartbeat written for crypto must not satisfy a query for us/india."""
        hm, data_dir = monitor
        _write_flat(data_dir, market="crypto", age_seconds=10)
        assert hm.get_heartbeat("us") is None
        assert hm.is_alive("us") is False
        assert "us" not in hm.get_all_heartbeats()

    def test_both_market_attributes_to_crypto_and_india(self, monitor):
        """``--market both`` mode: one file fans out to two per-market readers."""
        hm, data_dir = monitor
        _write_flat(data_dir, market="both", age_seconds=10)
        all_hb = hm.get_all_heartbeats()
        assert set(all_hb.keys()) == {"crypto", "india"}
        assert hm.is_alive("crypto") is True
        assert hm.is_alive("india") is True
        assert hm.is_alive("us") is False
