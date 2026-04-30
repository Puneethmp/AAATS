"""
Settlement risk manager for Indian equity markets (NSE T+1 settlement).

Tracks trade settlement dates, flags unsettled positions,
and ensures compliance with NSE rolling settlement rules.

Usage:
    from risk.settlement_manager import SettlementManager
    sm = SettlementManager()
    sm.record_trade_settlement("RELIANCE", "BUY", trade_date="2024-01-15", shares=10, price=2900.0)
    unsettled = sm.get_unsettled_positions()
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("risk", "settlement_manager")
_DB = Path("data/settlement.db")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            settlement_date TEXT NOT NULL,
            shares REAL NOT NULL,
            price REAL NOT NULL,
            settled INTEGER NOT NULL DEFAULT 0,
            settlement_amount REAL NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_settle_date ON settlements(settlement_date, settled)")
    conn.commit()


def _next_trading_day(d: date, days: int) -> date:
    """Add N trading days (skips weekends, approximate)."""
    result = d
    added = 0
    while added < days:
        result += timedelta(days=1)
        if result.weekday() < 5:  # Mon-Fri
            added += 1
    return result


class SettlementManager:
    """Tracks NSE T+1 settlement cycles for India equity trades."""

    def __init__(self, db_path: Path | None = None, settlement_days: int = 1) -> None:
        self._db = db_path or _DB
        self._settlement_days = settlement_days
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def record_trade_settlement(
        self,
        symbol: str,
        side: str,
        shares: float,
        price: float,
        trade_date: str | None = None,
    ) -> str:
        """Record a trade for settlement tracking. Returns settlement date string."""
        td = date.fromisoformat(trade_date) if trade_date else date.today()
        sd = _next_trading_day(td, self._settlement_days)
        amount = shares * price
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """INSERT INTO settlements (symbol, side, trade_date, settlement_date, shares, price, settlement_amount, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (symbol, side, td.isoformat(), sd.isoformat(), shares, price, amount, time.time()),
            )
        _log.info(f"Settlement recorded: {symbol} {side} T+{self._settlement_days} → {sd}")
        return sd.isoformat()

    def get_unsettled_positions(self, as_of: str | None = None) -> list[dict]:
        """Return positions pending settlement as of a given date (defaults to today)."""
        cutoff = as_of or date.today().isoformat()
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                """SELECT symbol, side, trade_date, settlement_date, shares, price, settlement_amount
                   FROM settlements WHERE settled=0 AND settlement_date <= ?
                   ORDER BY settlement_date""",
                (cutoff,),
            ).fetchall()
        return [
            {
                "symbol": r[0], "side": r[1], "trade_date": r[2],
                "settlement_date": r[3], "shares": r[4], "price": r[5],
                "amount": r[6],
            }
            for r in rows
        ]

    def mark_settled(self, symbol: str, settlement_date: str) -> int:
        """Mark settlements as complete. Returns number of records updated."""
        with sqlite3.connect(self._db) as conn:
            result = conn.execute(
                "UPDATE settlements SET settled=1 WHERE symbol=? AND settlement_date=? AND settled=0",
                (symbol, settlement_date),
            )
            return result.rowcount

    def get_settlement_risk(self) -> float:
        """Return total unsettled notional value (settlement exposure)."""
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT SUM(settlement_amount) FROM settlements WHERE settled=0"
            ).fetchone()
        return row[0] or 0.0
