"""
Compliance audit logger for AAATS.

Provides an immutable, append-only audit log for all compliance-relevant events:
  - Mode switches (paper ↔ live)
  - Kill switch activations
  - Credential access
  - Strategy parameter changes
  - Any RBAC permission checks

Separate from the operational audit trail in foundation/audit_trail.py —
this one is specifically for regulatory/compliance use.

Usage:
    from compliance.audit_logger import ComplianceAuditLogger
    logger = ComplianceAuditLogger()
    logger.log("MODE_SWITCH", "PAPER→LIVE", actor="Puneeth", market="all")
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("compliance", "audit_logger")
_DB = Path("data/compliance_audit.db")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compliance_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            market TEXT NOT NULL DEFAULT 'all',
            details TEXT NOT NULL DEFAULT '{}',
            ip_address TEXT NOT NULL DEFAULT 'local'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON compliance_audit(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_type ON compliance_audit(event_type)")
    conn.commit()


class ComplianceAuditLogger:
    """
    Append-only compliance audit log. Records must never be modified or deleted.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def log(
        self,
        event_type: str,
        description: str,
        actor: str = "system",
        market: str = "all",
        details: dict | None = None,
    ) -> int:
        """Append an immutable audit record. Returns the record ID."""
        with sqlite3.connect(self._db) as conn:
            cursor = conn.execute(
                "INSERT INTO compliance_audit (timestamp, event_type, description, actor, market, details) VALUES (?,?,?,?,?,?)",
                (time.time(), event_type, description, actor, market, json.dumps(details or {})),
            )
            record_id = cursor.lastrowid
        _log.info(f"Compliance audit: [{event_type}] {description} | actor={actor}")
        return record_id

    def get_events(
        self,
        event_type: str | None = None,
        since_hours: int = 168,
        limit: int = 500,
    ) -> list[dict]:
        cutoff = time.time() - since_hours * 3600
        with sqlite3.connect(self._db) as conn:
            if event_type:
                rows = conn.execute(
                    "SELECT id, timestamp, event_type, description, actor, market, details FROM compliance_audit WHERE event_type=? AND timestamp > ? ORDER BY timestamp DESC LIMIT ?",
                    (event_type, cutoff, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, timestamp, event_type, description, actor, market, details FROM compliance_audit WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
                    (cutoff, limit),
                ).fetchall()
        return [
            {
                "id": r[0], "timestamp": r[1], "event_type": r[2],
                "description": r[3], "actor": r[4], "market": r[5],
                "details": json.loads(r[6]),
            }
            for r in rows
        ]

    def export_csv(self, output_path: Path | None = None) -> Path:
        """Export full audit log to CSV for regulatory submission."""
        import csv
        out = output_path or Path("reports/compliance/audit_export.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                "SELECT id, timestamp, event_type, description, actor, market, details FROM compliance_audit ORDER BY timestamp"
            ).fetchall()
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "timestamp", "event_type", "description", "actor", "market", "details"])
            writer.writerows(rows)
        _log.info(f"Audit log exported: {out} ({len(rows)} records)")
        return out
