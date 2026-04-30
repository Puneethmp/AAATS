"""
Partial fill handler for AAATS.

Tracks orders that were only partially filled and manages
retry logic, position reconciliation, and reporting.

Usage:
    from execution.partial_fill_handler import PartialFillHandler
    pfh = PartialFillHandler()
    pfh.record_partial_fill("BTC/USDT", "BUY", ordered=0.1, filled=0.07, price=50000.0)
    unfilled = pfh.get_pending_fills()
    pfh.retry_pending_fills()  # call periodically
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("execution", "partial_fill_handler")
_DB = Path("data/partial_fills.db")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS partial_fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            ordered_shares REAL NOT NULL,
            filled_shares REAL NOT NULL,
            unfilled_shares REAL NOT NULL,
            price REAL NOT NULL,
            fill_pct REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pf_status ON partial_fills(status, created_at)")
    conn.commit()


class PartialFillHandler:
    """Tracks and manages partially filled orders."""

    def __init__(self, db_path: Path | None = None, max_retries: int = 3) -> None:
        self._db = db_path or _DB
        self._max_retries = max_retries
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def record_partial_fill(
        self,
        symbol: str,
        side: str,
        ordered: float,
        filled: float,
        price: float,
        market: str = "crypto",
    ) -> None:
        """Record a partial fill for later retry."""
        unfilled = ordered - filled
        fill_pct = filled / max(ordered, 1e-9)
        now = time.time()
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """INSERT INTO partial_fills
                   (market, symbol, side, ordered_shares, filled_shares, unfilled_shares, price, fill_pct, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (market, symbol, side, ordered, filled, unfilled, price, fill_pct, now, now),
            )
        _log.warning(
            f"Partial fill: {market}/{symbol} {side} | filled={filled:.4f}/{ordered:.4f} ({fill_pct:.1%})"
        )

    def get_pending_fills(self, market: str | None = None) -> list[dict]:
        """Return all pending partial fills."""
        with sqlite3.connect(self._db) as conn:
            if market:
                rows = conn.execute(
                    "SELECT id, market, symbol, side, unfilled_shares, price, retry_count, created_at FROM partial_fills WHERE status='PENDING' AND market=? ORDER BY created_at",
                    (market,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, market, symbol, side, unfilled_shares, price, retry_count, created_at FROM partial_fills WHERE status='PENDING' ORDER BY created_at"
                ).fetchall()
        return [
            {"id": r[0], "market": r[1], "symbol": r[2], "side": r[3],
             "unfilled_shares": r[4], "price": r[5], "retry_count": r[6], "created_at": r[7]}
            for r in rows
        ]

    def mark_completed(self, fill_id: int) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "UPDATE partial_fills SET status='COMPLETED', updated_at=? WHERE id=?",
                (time.time(), fill_id),
            )

    def mark_abandoned(self, fill_id: int, reason: str = "") -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "UPDATE partial_fills SET status='ABANDONED', updated_at=? WHERE id=?",
                (time.time(), fill_id),
            )
        _log.warning(f"Partial fill {fill_id} abandoned: {reason}")

    def increment_retry(self, fill_id: int) -> int:
        """Increment retry count. Returns new count."""
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "UPDATE partial_fills SET retry_count=retry_count+1, updated_at=? WHERE id=?",
                (time.time(), fill_id),
            )
            row = conn.execute("SELECT retry_count FROM partial_fills WHERE id=?", (fill_id,)).fetchone()
        return row[0] if row else 0

    def abandon_expired_fills(self, max_age_seconds: int = 3600) -> int:
        """Mark fills older than max_age as abandoned. Returns count."""
        cutoff = time.time() - max_age_seconds
        with sqlite3.connect(self._db) as conn:
            result = conn.execute(
                "UPDATE partial_fills SET status='ABANDONED', updated_at=? WHERE status='PENDING' AND created_at < ?",
                (time.time(), cutoff),
            )
            return result.rowcount
