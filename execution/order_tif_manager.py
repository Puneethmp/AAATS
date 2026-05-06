"""
Order Time-In-Force (TIF) manager for AAATS.

Manages order validity periods:
  - GTC (Good-Till-Cancelled): active until filled or cancelled
  - GTD (Good-Till-Date): expires at specific date/time
  - IOC (Immediate-Or-Cancel): fill immediately or cancel
  - FOK (Fill-Or-Kill): fill entirely immediately or cancel
  - DAY: valid only for current trading session

Usage:
    from execution.order_tif_manager import OrderTIFManager, TIF
    tif_mgr = OrderTIFManager()
    tif_mgr.submit_order("BTC/USDT", "BUY", 0.01, 50000.0, tif=TIF.GTC)
    tif_mgr.expire_orders()  # call periodically to clean up
"""

from __future__ import annotations

import sqlite3
import time
from enum import Enum
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("execution", "order_tif_manager")
_DB = Path("data/tif_orders.db")


class TIF(str, Enum):
    GTC = "GTC"   # Good-Till-Cancelled
    GTD = "GTD"   # Good-Till-Date
    IOC = "IOC"   # Immediate-Or-Cancel
    FOK = "FOK"   # Fill-Or-Kill
    DAY = "DAY"   # Today only


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tif_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            shares REAL NOT NULL,
            price REAL NOT NULL,
            tif TEXT NOT NULL,
            expires_at REAL,
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    conn.commit()


class OrderTIFManager:
    """Tracks orders with time-in-force rules and expires stale orders."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def submit_order(
        self,
        symbol: str,
        side: str,
        shares: float,
        price: float,
        tif: TIF = TIF.GTC,
        market: str = "crypto",
        expires_at: float | None = None,
    ) -> int:
        """Record an order. Returns the order ID."""
        now = time.time()
        if tif == TIF.DAY:
            expires_at = expires_at or (now + 86400)
        elif tif == TIF.IOC or tif == TIF.FOK:
            expires_at = now + 60  # expires after 60 seconds
        with sqlite3.connect(self._db) as conn:
            cursor = conn.execute(
                """INSERT INTO tif_orders (market, symbol, side, shares, price, tif, expires_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (market, symbol, side, shares, price, tif.value, expires_at, now, now),
            )
            return cursor.lastrowid

    def expire_orders(self) -> int:
        """Mark expired orders as EXPIRED. Returns count of expired orders."""
        now = time.time()
        with sqlite3.connect(self._db) as conn:
            result = conn.execute(
                "UPDATE tif_orders SET status='EXPIRED', updated_at=? WHERE status='ACTIVE' AND expires_at IS NOT NULL AND expires_at < ?",
                (now, now),
            )
            count = result.rowcount
        if count:
            _log.info(f"Expired {count} TIF order(s)")
        return count

    def fill_order(self, order_id: int) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "UPDATE tif_orders SET status='FILLED', updated_at=? WHERE id=?",
                (time.time(), order_id),
            )

    def cancel_order(self, order_id: int) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "UPDATE tif_orders SET status='CANCELLED', updated_at=? WHERE id=?",
                (time.time(), order_id),
            )

    def get_active_orders(self, market: str | None = None) -> list[dict]:
        with sqlite3.connect(self._db) as conn:
            if market:
                rows = conn.execute(
                    "SELECT id, market, symbol, side, shares, price, tif, expires_at FROM tif_orders WHERE status='ACTIVE' AND market=?",
                    (market,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, market, symbol, side, shares, price, tif, expires_at FROM tif_orders WHERE status='ACTIVE'"
                ).fetchall()
        return [
            {"id": r[0], "market": r[1], "symbol": r[2], "side": r[3],
             "shares": r[4], "price": r[5], "tif": r[6], "expires_at": r[7]}
            for r in rows
        ]
