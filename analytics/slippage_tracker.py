"""
Slippage tracker for AAATS.

Records the difference between expected and actual fill prices,
tracks average slippage in basis points (bps), and alerts on large slippage.

Usage:
    from analytics.slippage_tracker import SlippageTracker
    st = SlippageTracker()
    st.record_slippage("BTC/USDT", expected=50000.0, actual=50050.0, side="BUY", market="crypto")
    avg = st.average_slippage_bps(market="crypto")
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("analytics", "slippage_tracker")
_DB = Path("data/slippage.db")
_WARN_BPS = 30.0   # warn if single trade slippage > 30 bps


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS slippage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            expected_price REAL NOT NULL,
            actual_price REAL NOT NULL,
            slippage_bps REAL NOT NULL,
            notional REAL NOT NULL DEFAULT 0.0,
            recorded_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_slip_market ON slippage(market, recorded_at)")
    conn.commit()


class SlippageTracker:
    """Records and analyzes execution slippage in basis points."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def record_slippage(
        self,
        symbol: str,
        expected: float,
        actual: float,
        side: str,
        market: str,
        shares: float = 0.0,
    ) -> float:
        """Record slippage between expected and actual fill. Returns slippage in bps."""
        if expected <= 0:
            return 0.0
        # For BUY: positive slippage = paid more than expected (worse)
        # For SELL: positive slippage = received less than expected (worse)
        if side.upper() == "BUY":
            raw = (actual - expected) / expected
        else:
            raw = (expected - actual) / expected
        bps = raw * 10_000
        notional = actual * shares
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """INSERT INTO slippage (market, symbol, side, expected_price, actual_price, slippage_bps, notional, recorded_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (market, symbol, side, expected, actual, bps, notional, time.time()),
            )
        if abs(bps) > _WARN_BPS:
            _log.warning(f"HIGH SLIPPAGE: {market}/{symbol} {side} | {bps:.1f} bps")
        else:
            _log.debug(f"Slippage: {market}/{symbol} {side} | {bps:.1f} bps")
        return bps

    def average_slippage_bps(self, market: str | None = None, since_hours: int = 24) -> float:
        """Return average absolute slippage in bps over the last N hours."""
        cutoff = time.time() - since_hours * 3600
        with sqlite3.connect(self._db) as conn:
            if market:
                row = conn.execute(
                    "SELECT AVG(ABS(slippage_bps)) FROM slippage WHERE market=? AND recorded_at > ?",
                    (market, cutoff),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT AVG(ABS(slippage_bps)) FROM slippage WHERE recorded_at > ?",
                    (cutoff,),
                ).fetchone()
        return row[0] or 0.0

    def get_recent(self, market: str | None = None, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self._db) as conn:
            if market:
                rows = conn.execute(
                    "SELECT market, symbol, side, slippage_bps, notional, recorded_at FROM slippage WHERE market=? ORDER BY recorded_at DESC LIMIT ?",
                    (market, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT market, symbol, side, slippage_bps, notional, recorded_at FROM slippage ORDER BY recorded_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {"market": r[0], "symbol": r[1], "side": r[2], "slippage_bps": r[3], "notional": r[4], "at": r[5]}
            for r in rows
        ]
