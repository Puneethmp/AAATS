"""
Tests for foundation/audit_trail.py.
Verifies append-only enforcement, hash integrity, and query filtering.
"""

from pathlib import Path

import pytest


@pytest.fixture
def trail(tmp_path):
    from foundation.audit_trail import AuditTrail

    return AuditTrail(db_path=str(tmp_path / "test_audit.db"))


class TestAppend:
    def test_append_creates_queryable_entry(self, trail):
        trail.append(
            market="us",
            module="test",
            event_type="SIGNAL",
            details={"symbol": "AAPL", "action": "BUY"},
            result="GO",
            reason="Momentum crossover",
        )
        rows = trail.query(market="us")
        assert len(rows) == 1
        assert rows[0]["market"] == "us"
        assert rows[0]["details"]["symbol"] == "AAPL"
        assert rows[0]["result"] == "GO"

    def test_append_returns_hash_string(self, trail):
        h = trail.append(
            market="india",
            module="test",
            event_type="ORDER",
            details={"symbol": "RELIANCE"},
            result="GO",
            reason="Strategy signal",
        )
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest length

    def test_multiple_entries_ordered_by_id(self, trail):
        for i in range(3):
            trail.append(
                market="us",
                module="test",
                event_type="SIGNAL",
                details={"i": i},
                result="GO",
                reason=f"entry {i}",
            )
        rows = trail.query(market="us")
        ids = [r["id"] for r in rows]
        assert ids == sorted(ids)


class TestAppendOnly:
    def test_update_raises_permission_error(self, trail):
        with pytest.raises(PermissionError):
            trail.update(id=1, result="REJECTED")

    def test_delete_raises_permission_error(self, trail):
        with pytest.raises(PermissionError):
            trail.delete(id=1)

    def test_update_with_no_args_still_raises(self, trail):
        with pytest.raises(PermissionError):
            trail.update()

    def test_delete_with_no_args_still_raises(self, trail):
        with pytest.raises(PermissionError):
            trail.delete()


class TestHashIntegrity:
    def test_clean_entries_pass_verification(self, trail):
        trail.append(
            market="india",
            module="test",
            event_type="HALT",
            details={"reason": "drawdown"},
            result="HALTED",
            reason="Drawdown -15% hit",
        )
        rows = trail.query(market="india", verify_hashes=True)
        assert len(rows) == 1

    def test_tampered_reason_detected(self, trail):
        from sqlalchemy import text

        trail.append(
            market="us",
            module="test",
            event_type="SIGNAL",
            details={},
            result="GO",
            reason="Original reason",
        )

        # Tamper directly in the DB
        with trail._engine.connect() as conn:
            conn.execute(text("UPDATE audit_log SET reason = 'tampered' WHERE id = 1"))
            conn.commit()

        with pytest.raises(ValueError, match="integrity violation"):
            trail.query(market="us", verify_hashes=True)

    def test_tampered_result_detected(self, trail):
        from sqlalchemy import text

        trail.append(
            market="us",
            module="test",
            event_type="RISK_CHECK",
            details={"size": 100},
            result="NO_GO",
            reason="Over position limit",
        )

        with trail._engine.connect() as conn:
            conn.execute(text("UPDATE audit_log SET result = 'GO' WHERE id = 1"))
            conn.commit()

        with pytest.raises(ValueError, match="integrity violation"):
            trail.query(verify_hashes=True)

    def test_skip_hash_verification(self, trail):
        from sqlalchemy import text

        trail.append(
            market="us",
            module="test",
            event_type="SIGNAL",
            details={},
            result="GO",
            reason="ok",
        )

        with trail._engine.connect() as conn:
            conn.execute(text("UPDATE audit_log SET reason = 'tampered' WHERE id = 1"))
            conn.commit()

        # Should NOT raise when verify_hashes=False
        rows = trail.query(verify_hashes=False)
        assert rows[0]["reason"] == "tampered"


class TestQuery:
    def test_filter_by_market(self, trail):
        trail.append(market="us", module="t", event_type="SIGNAL", details={}, result="GO", reason="r")
        trail.append(market="india", module="t", event_type="SIGNAL", details={}, result="GO", reason="r")

        us_rows = trail.query(market="us")
        assert len(us_rows) == 1
        assert us_rows[0]["market"] == "us"

    def test_filter_by_event_type(self, trail):
        trail.append(market="us", module="t", event_type="SIGNAL", details={}, result="GO", reason="r")
        trail.append(market="us", module="t", event_type="HALT", details={}, result="HALTED", reason="r")

        halts = trail.query(event_type="HALT")
        assert len(halts) == 1
        assert halts[0]["event_type"] == "HALT"

    def test_no_filter_returns_all(self, trail):
        for _ in range(5):
            trail.append(market="us", module="t", event_type="SIGNAL", details={}, result="GO", reason="r")
        assert len(trail.query()) == 5

    def test_details_returned_as_dict(self, trail):
        trail.append(
            market="us",
            module="t",
            event_type="ORDER",
            details={"symbol": "TSLA", "qty": 10},
            result="GO",
            reason="ok",
        )
        rows = trail.query()
        assert isinstance(rows[0]["details"], dict)
        assert rows[0]["details"]["symbol"] == "TSLA"
