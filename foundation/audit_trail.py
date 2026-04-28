"""
Immutable, tamper-evident audit trail for AAATS.
Every trading decision, signal, order, halt, and rejection is logged here.

Rules enforced in code:
  - append() is the only write method — no UPDATE or DELETE.
  - Every entry is SHA-256 hashed at write time.
  - Hash is verified on every read — tampered entries raise ValueError immediately.

Usage:
    from foundation.audit_trail import AuditTrail
    trail = AuditTrail()
    trail.append(market="us", module="decision_engine", event_type="SIGNAL",
                 details={"symbol": "AAPL", "action": "BUY"}, result="GO", reason="Momentum signal")
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

EventType = Literal["SIGNAL", "RISK_CHECK", "ORDER", "REJECTION", "HALT", "RETRAIN", "HEALTH", "TOKEN_RENEWAL"]
ResultType = Literal["GO", "NO_GO", "HALTED", "REJECTED", "SUCCESS", "FAILURE"]


class AuditTrail:
    """
    Append-only SQLite-backed audit log with SHA-256 hash integrity.

    Args:
        db_path: Path to the SQLite database file. Created on first use.
    """

    def __init__(self, db_path: str = "data/audit_trail.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._engine = sa.create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self._init_schema()

    def _init_schema(self) -> None:
        with self._engine.connect() as conn:
            conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp   TEXT    NOT NULL,
                        market      TEXT    NOT NULL,
                        module      TEXT    NOT NULL,
                        event_type  TEXT    NOT NULL,
                        details     TEXT    NOT NULL,
                        result      TEXT    NOT NULL,
                        reason      TEXT    NOT NULL,
                        entry_hash  TEXT    NOT NULL
                    )
                """)
            )
            conn.commit()

    @staticmethod
    def _compute_hash(
        timestamp: str,
        market: str,
        event_type: str,
        details: str,
        result: str,
        reason: str,
    ) -> str:
        payload = f"{timestamp}|{market}|{event_type}|{details}|{result}|{reason}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def append(
        self,
        market: str,
        module: str,
        event_type: EventType,
        details: dict[str, Any],
        result: ResultType,
        reason: str,
    ) -> str:
        """
        Write one immutable entry to the audit log.

        Args:
            market:     Market this event belongs to ("us", "india", "crypto", "system").
            module:     Module that generated this event (e.g. "kill_switch").
            event_type: Category of event — SIGNAL, RISK_CHECK, ORDER, REJECTION, HALT, etc.
            details:    Arbitrary context dict (serialised to JSON).
            result:     Outcome — GO, NO_GO, HALTED, REJECTED, SUCCESS, or FAILURE.
            reason:     Human-readable explanation, stored verbatim.

        Returns:
            The SHA-256 hex digest of this entry (for external cross-referencing).
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        details_str = json.dumps(details, sort_keys=True, default=str)
        entry_hash = self._compute_hash(timestamp, market, event_type, details_str, result, reason)

        with self._engine.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO audit_log
                        (timestamp, market, module, event_type, details, result, reason, entry_hash)
                    VALUES
                        (:timestamp, :market, :module, :event_type, :details, :result, :reason, :entry_hash)
                """),
                {
                    "timestamp": timestamp,
                    "market": market,
                    "module": module,
                    "event_type": event_type,
                    "details": details_str,
                    "result": result,
                    "reason": reason,
                    "entry_hash": entry_hash,
                },
            )
            conn.commit()

        return entry_hash

    def update(self, *args: Any, **kwargs: Any) -> None:
        """Permanently blocked — AuditTrail is append-only."""
        raise PermissionError(
            "AuditTrail is append-only. UPDATE operations are permanently prohibited. "
            "Create a new corrective entry via append() instead."
        )

    def delete(self, *args: Any, **kwargs: Any) -> None:
        """Permanently blocked — AuditTrail is append-only."""
        raise PermissionError(
            "AuditTrail is append-only. DELETE operations are permanently prohibited."
        )

    def query(
        self,
        market: Optional[str] = None,
        event_type: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        verify_hashes: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Read entries from the audit log with optional filters.
        Raises ValueError immediately if any entry fails hash verification.

        Args:
            market:        Filter by market tag. None = all markets.
            event_type:    Filter by event type. None = all types.
            start:         ISO-8601 timestamp lower bound (inclusive).
            end:           ISO-8601 timestamp upper bound (inclusive).
            verify_hashes: When True (default), re-computes and checks every hash.

        Returns:
            List of dicts with keys matching the audit_log schema.
            'details' is returned as a parsed dict (not a JSON string).
        """
        conditions: list[str] = []
        params: dict[str, Any] = {}

        if market:
            conditions.append("market = :market")
            params["market"] = market
        if event_type:
            conditions.append("event_type = :event_type")
            params["event_type"] = event_type
        if start:
            conditions.append("timestamp >= :start")
            params["start"] = start
        if end:
            conditions.append("timestamp <= :end")
            params["end"] = end

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM audit_log {where} ORDER BY id ASC"),
                params,
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row._mapping)

            if verify_hashes:
                expected = self._compute_hash(
                    record["timestamp"],
                    record["market"],
                    record["event_type"],
                    record["details"],
                    record["result"],
                    record["reason"],
                )
                if expected != record["entry_hash"]:
                    raise ValueError(
                        f"Audit trail integrity violation: entry id={record['id']} "
                        f"hash mismatch. Expected {expected[:16]}… "
                        f"got {record['entry_hash'][:16]}…. "
                        "The database may have been tampered with."
                    )

            record["details"] = json.loads(record["details"])
            results.append(record)

        return results
