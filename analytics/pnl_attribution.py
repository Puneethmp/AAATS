"""
PnL attribution tracker for AAATS.

Records trade-level PnL broken down by market, strategy, and regime.
Provides aggregated reporting for performance analysis.

Usage:
    from analytics.pnl_attribution import PnLAttribution
    pa = PnLAttribution()
    pa.record_trade(market="crypto", symbol="BTC/USDT", strategy="grid",
                    regime="BULL_TREND", pnl=127.5, side="SELL")
    df = pa.get_summary()
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("analytics", "pnl_attribution")
_DB = Path("data/pnl_attribution.db")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            strategy TEXT NOT NULL DEFAULT 'default',
            regime TEXT NOT NULL DEFAULT 'UNKNOWN',
            side TEXT NOT NULL,
            pnl REAL NOT NULL,
            pnl_pct REAL NOT NULL DEFAULT 0.0,
            entry_price REAL NOT NULL DEFAULT 0.0,
            exit_price REAL NOT NULL DEFAULT 0.0,
            shares REAL NOT NULL DEFAULT 0.0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pnl_market ON trade_pnl(market, timestamp)")
    conn.commit()


class PnLAttribution:
    """Records and aggregates trade-level PnL for attribution analysis."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def record_trade(
        self,
        market: str,
        symbol: str,
        pnl: float,
        side: str = "SELL",
        strategy: str = "default",
        regime: str = "UNKNOWN",
        entry_price: float = 0.0,
        exit_price: float = 0.0,
        shares: float = 0.0,
    ) -> None:
        cost = entry_price * shares
        pnl_pct = pnl / max(cost, 1e-9)
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """INSERT INTO trade_pnl
                   (timestamp, market, symbol, strategy, regime, side, pnl, pnl_pct, entry_price, exit_price, shares)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (time.time(), market, symbol, strategy, regime, side, pnl, pnl_pct,
                 entry_price, exit_price, shares),
            )
        _log.debug(f"PnL recorded: {market}/{symbol} | pnl={pnl:.4f} | regime={regime}")

    def get_summary(self, market: str | None = None) -> list[dict]:
        """Return per-market, per-strategy aggregated PnL."""
        with sqlite3.connect(self._db) as conn:
            if market:
                rows = conn.execute(
                    """SELECT market, strategy, regime,
                              COUNT(*) as trades,
                              SUM(pnl) as total_pnl,
                              AVG(pnl) as avg_pnl,
                              SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
                       FROM trade_pnl WHERE market=? GROUP BY market, strategy, regime""",
                    (market,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT market, strategy, regime,
                              COUNT(*) as trades,
                              SUM(pnl) as total_pnl,
                              AVG(pnl) as avg_pnl,
                              SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
                       FROM trade_pnl GROUP BY market, strategy, regime"""
                ).fetchall()
        return [
            {
                "market": r[0], "strategy": r[1], "regime": r[2],
                "trades": r[3], "total_pnl": r[4] or 0.0,
                "avg_pnl": r[5] or 0.0,
                "win_rate": (r[6] / r[3]) if r[3] > 0 else 0.0,
            }
            for r in rows
        ]

    def total_pnl(self, market: str | None = None) -> float:
        with sqlite3.connect(self._db) as conn:
            if market:
                row = conn.execute(
                    "SELECT SUM(pnl) FROM trade_pnl WHERE market=?", (market,)
                ).fetchone()
            else:
                row = conn.execute("SELECT SUM(pnl) FROM trade_pnl").fetchone()
        return row[0] or 0.0
