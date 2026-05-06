"""
Persistent position manager for AAATS.

Persists open positions to SQLite so they survive process restarts.
Detects drift between in-memory state and DB state on startup.

Usage:
    from risk.position_manager import PersistentPositionManager
    pm = PersistentPositionManager(market="crypto")
    pm.open_position("BTC/USDT", entry_price=50000.0, shares=0.01)
    pm.close_position("BTC/USDT", exit_price=51000.0)
    positions = pm.get_open_positions()
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import os as _os

from foundation.logger import get_logger

_log = get_logger("risk", "position_manager")
_DB = Path(_os.environ.get("AAATS_DATA", "data")) / "positions.db"


@dataclass
class Position:
    symbol: str
    market: str
    entry_price: float
    shares: float
    entry_time: float
    metadata: dict


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            entry_price REAL NOT NULL,
            shares REAL NOT NULL,
            entry_time REAL NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            closed INTEGER NOT NULL DEFAULT 0,
            exit_price REAL,
            exit_time REAL,
            pnl REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pos_market ON positions(market, closed)")
    conn.commit()


class PersistentPositionManager:
    """
    Manages open positions with SQLite persistence.
    Thread-safe via connection-per-call pattern.
    """

    def __init__(self, market: str, db_path: Path | None = None) -> None:
        self._market = market
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db)

    def open_position(
        self,
        symbol: str,
        entry_price: float,
        shares: float,
        metadata: dict | None = None,
    ) -> None:
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM positions WHERE symbol=? AND market=? AND closed=0",
                (symbol, self._market),
            ).fetchone()
            if existing:
                _log.warning(f"Position already open for {symbol}/{self._market} — skipping duplicate")
                return
            conn.execute(
                """INSERT INTO positions (symbol, market, entry_price, shares, entry_time, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (symbol, self._market, entry_price, shares, time.time(), json.dumps(metadata or {})),
            )
        _log.info(f"Position opened: {self._market}/{symbol} @ {entry_price} x {shares}")

    def close_position(self, symbol: str, exit_price: float) -> Optional[float]:
        """Close position and return realized PnL, or None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, entry_price, shares FROM positions WHERE symbol=? AND market=? AND closed=0",
                (symbol, self._market),
            ).fetchone()
            if not row:
                _log.warning(f"No open position found for {symbol}/{self._market}")
                return None
            pos_id, entry_price, shares = row
            pnl = round((exit_price - entry_price) * shares, 6)
            conn.execute(
                "UPDATE positions SET closed=1, exit_price=?, exit_time=?, pnl=? WHERE id=?",
                (exit_price, time.time(), pnl, pos_id),
            )
        _log.info(f"Position closed: {self._market}/{symbol} @ {exit_price} | PnL={pnl:.4f}")
        return pnl

    def get_open_positions(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT symbol, entry_price, shares, entry_time, metadata FROM positions WHERE market=? AND closed=0",
                (self._market,),
            ).fetchall()
        return [
            {
                "symbol": r[0],
                "entry_price": r[1],
                "shares": r[2],
                "entry_time": r[3],
                "metadata": json.loads(r[4]),
            }
            for r in rows
        ]

    def has_open_position(self, symbol: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM positions WHERE symbol=? AND market=? AND closed=0",
                (symbol, self._market),
            ).fetchone()
        return row is not None

    def reconcile(self, live_symbols: set[str]) -> list[str]:
        """Compare DB open positions to live broker state. Returns list of drift symbols."""
        db_open = {p["symbol"] for p in self.get_open_positions()}
        drifts = list(db_open.symmetric_difference(live_symbols))
        if drifts:
            _log.warning(f"Position drift detected for {self._market}: {drifts}")
        return drifts
