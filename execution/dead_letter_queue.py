"""
Dead Letter Queue (DLQ) for AAATS.

Failed orders that couldn't be processed after max retries are moved here.
A background task retries DLQ items every 5 minutes.

Usage:
    from execution.dead_letter_queue import DeadLetterQueue
    dlq = DeadLetterQueue()
    dlq.enqueue("BTC/USDT", "BUY", 0.01, 50000.0, error="Rate limit exceeded")
    items = dlq.get_pending()
    dlq.retry_all()  # attempt to re-process all pending items
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable

from foundation.logger import get_logger

_log = get_logger("execution", "dead_letter_queue")
_DB = Path("data/dead_letter_queue.db")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dlq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            shares REAL NOT NULL,
            price REAL NOT NULL,
            error TEXT NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            status TEXT NOT NULL DEFAULT 'PENDING',
            next_retry_at REAL NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    conn.commit()


class DeadLetterQueue:
    """
    Stores failed orders for retry processing.
    Items that exceed max_retries are marked as DEAD.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        retry_delay_seconds: int = 300,
        max_retries: int = 3,
    ) -> None:
        self._db = db_path or _DB
        self._retry_delay = retry_delay_seconds
        self._max_retries = max_retries
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def enqueue(
        self,
        symbol: str,
        side: str,
        shares: float,
        price: float,
        error: str,
        market: str = "crypto",
    ) -> int:
        """Add a failed order to the DLQ. Returns the DLQ item ID."""
        now = time.time()
        with sqlite3.connect(self._db) as conn:
            cursor = conn.execute(
                """INSERT INTO dlq (market, symbol, side, shares, price, error, max_retries, next_retry_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (market, symbol, side, shares, price, error, self._max_retries,
                 now + self._retry_delay, now, now),
            )
            item_id = cursor.lastrowid
        _log.warning(f"DLQ: enqueued {market}/{symbol} {side} — {error} (id={item_id})")
        return item_id

    def get_pending(self) -> list[dict]:
        """Return all items ready for retry."""
        now = time.time()
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                """SELECT id, market, symbol, side, shares, price, error, retry_count, max_retries
                   FROM dlq WHERE status='PENDING' AND next_retry_at <= ?
                   ORDER BY created_at""",
                (now,),
            ).fetchall()
        return [
            {"id": r[0], "market": r[1], "symbol": r[2], "side": r[3],
             "shares": r[4], "price": r[5], "error": r[6],
             "retry_count": r[7], "max_retries": r[8]}
            for r in rows
        ]

    def mark_success(self, item_id: int) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "UPDATE dlq SET status='RESOLVED', updated_at=? WHERE id=?",
                (time.time(), item_id),
            )
        _log.info(f"DLQ item {item_id} resolved successfully")

    def mark_failed(self, item_id: int, error: str) -> None:
        now = time.time()
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT retry_count, max_retries FROM dlq WHERE id=?", (item_id,)
            ).fetchone()
            if not row:
                return
            retry_count, max_retries = row
            new_count = retry_count + 1
            if new_count >= max_retries:
                conn.execute(
                    "UPDATE dlq SET status='DEAD', retry_count=?, error=?, updated_at=? WHERE id=?",
                    (new_count, error, now, item_id),
                )
                _log.error(f"DLQ item {item_id} DEAD after {new_count} retries: {error}")
            else:
                next_retry = now + self._retry_delay * (2 ** new_count)  # exponential backoff
                conn.execute(
                    "UPDATE dlq SET retry_count=?, error=?, next_retry_at=?, updated_at=? WHERE id=?",
                    (new_count, error, next_retry, now, item_id),
                )

    def retry_all(self, handler: Callable[[dict], bool] | None = None) -> tuple[int, int]:
        """
        Retry all pending DLQ items. Returns (success_count, failure_count).
        handler: callable that receives an item dict and returns True on success.
        """
        pending = self.get_pending()
        success, failure = 0, 0
        for item in pending:
            if handler:
                try:
                    if handler(item):
                        self.mark_success(item["id"])
                        success += 1
                    else:
                        self.mark_failed(item["id"], "Handler returned False")
                        failure += 1
                except Exception as exc:
                    self.mark_failed(item["id"], str(exc))
                    failure += 1
            else:
                _log.debug(f"DLQ item {item['id']}: no handler registered")
        if pending:
            _log.info(f"DLQ retry: {success} success, {failure} failed, {len(pending)} total")
        return success, failure

    def stats(self) -> dict:
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM dlq GROUP BY status"
            ).fetchall()
        return {r[0]: r[1] for r in rows}
