"""
Live engine status store. Each market runner writes its state here every cycle.
The Streamlit dashboard reads this to show live bot status.

Table: engine_status
  market, last_run, regime, symbols_scanned, trades_today, status, error,
  heartbeat_ts, cycle_count
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from foundation.logger import get_logger

_log = get_logger("execution", "status_db")

_DEFAULT_DB = str(Path(__file__).parent.parent / "data" / "status.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS engine_status (
    market          TEXT PRIMARY KEY,
    last_run        TEXT,
    regime          TEXT,
    symbols_scanned INTEGER DEFAULT 0,
    trades_today    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'IDLE',
    error           TEXT DEFAULT '',
    heartbeat_ts    TEXT DEFAULT '',
    cycle_count     INTEGER DEFAULT 0
)
"""

_MIGRATE_COLS = [
    ("heartbeat_ts", "TEXT DEFAULT ''"),
    ("cycle_count",  "INTEGER DEFAULT 0"),
]


def _conn(db_path: str = _DEFAULT_DB) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(_CREATE)
    # Add new columns to existing DBs without breaking them
    for col, coldef in _MIGRATE_COLS:
        try:
            c.execute(f"ALTER TABLE engine_status ADD COLUMN {col} {coldef}")
        except sqlite3.OperationalError as exc:
            _log.debug(f"engine_status migration noop ({col}): {exc}")
    c.commit()
    return c


def mark_running(market: str, db_path: str = _DEFAULT_DB) -> None:
    """Mark a runner as RUNNING without clearing last cycle's regime/scan data.

    Called at the START of each cycle so the dashboard shows 'RUNNING' while
    preserving the previous cycle's regime and symbols_scanned for readability.
    """
    ts = datetime.now(timezone.utc).isoformat()
    c = _conn(db_path)
    c.execute(
        "INSERT INTO engine_status (market,last_run,status,heartbeat_ts) "
        "VALUES (?,?,'RUNNING',?) "
        "ON CONFLICT(market) DO UPDATE SET "
        "last_run=excluded.last_run, status='RUNNING', heartbeat_ts=excluded.heartbeat_ts",
        (market, ts, ts),
    )
    c.commit()
    c.close()


def write_heartbeat(market: str, db_path: str = _DEFAULT_DB) -> None:
    """Write a mid-cycle heartbeat timestamp.

    Called periodically inside the symbol loop so the dashboard knows the
    runner is still alive even during long processing cycles.
    """
    ts = datetime.now(timezone.utc).isoformat()
    c = _conn(db_path)
    c.execute(
        "UPDATE engine_status SET heartbeat_ts=? WHERE market=?",
        (ts, market),
    )
    if c.execute("SELECT changes()").fetchone()[0] == 0:
        # Row doesn't exist yet — insert a stub
        c.execute(
            "INSERT OR IGNORE INTO engine_status (market,heartbeat_ts,status) VALUES (?,?,'RUNNING')",
            (market, ts),
        )
    c.commit()
    c.close()


def upsert_status(
    market: str,
    regime: str = "",
    symbols_scanned: int = 0,
    trades_today: int = 0,
    status: str = "RUNNING",
    error: str = "",
    db_path: str = _DEFAULT_DB,
) -> None:
    """End-of-cycle full status update. Updates all fields including regime."""
    ts = datetime.now(timezone.utc).isoformat()
    c = _conn(db_path)
    c.execute(
        "INSERT INTO engine_status "
        "(market,last_run,regime,symbols_scanned,trades_today,status,error,heartbeat_ts,cycle_count) "
        "VALUES (?,?,?,?,?,?,?,?,1) "
        "ON CONFLICT(market) DO UPDATE SET "
        "last_run=excluded.last_run, regime=excluded.regime, "
        "symbols_scanned=excluded.symbols_scanned, trades_today=excluded.trades_today, "
        "status=excluded.status, error=excluded.error, heartbeat_ts=excluded.heartbeat_ts, "
        "cycle_count=cycle_count+1",
        (market, ts, regime, symbols_scanned, trades_today, status, error, ts),
    )
    c.commit()
    c.close()


def get_all_status(db_path: str = _DEFAULT_DB) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame(columns=[
            "market", "last_run", "regime", "symbols_scanned", "trades_today",
            "status", "error", "heartbeat_ts", "cycle_count",
        ])
    c = _conn(db_path)
    df = pd.read_sql_query("SELECT * FROM engine_status", c)
    c.close()
    return df
