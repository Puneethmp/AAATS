"""
Live engine status store. Each market runner writes its state here every cycle.
The Streamlit dashboard reads this to show live bot status.

Table: engine_status
  market, last_run, regime, symbols_scanned, trades_today, status, error
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

_DEFAULT_DB = str(Path(__file__).parent.parent / "data" / "status.db")

_CREATE = """
CREATE TABLE IF NOT EXISTS engine_status (
    market          TEXT PRIMARY KEY,
    last_run        TEXT,
    regime          TEXT,
    symbols_scanned INTEGER DEFAULT 0,
    trades_today    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'IDLE',
    error           TEXT DEFAULT ''
)
"""


def _conn(db_path: str = _DEFAULT_DB) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path, check_same_thread=False)
    c.execute(_CREATE)
    c.commit()
    return c


def upsert_status(
    market: str,
    regime: str = "",
    symbols_scanned: int = 0,
    trades_today: int = 0,
    status: str = "RUNNING",
    error: str = "",
    db_path: str = _DEFAULT_DB,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    c = _conn(db_path)
    c.execute(
        "INSERT INTO engine_status (market,last_run,regime,symbols_scanned,trades_today,status,error) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(market) DO UPDATE SET "
        "last_run=excluded.last_run, regime=excluded.regime, "
        "symbols_scanned=excluded.symbols_scanned, trades_today=excluded.trades_today, "
        "status=excluded.status, error=excluded.error",
        (market, ts, regime, symbols_scanned, trades_today, status, error),
    )
    c.commit()
    c.close()


def get_all_status(db_path: str = _DEFAULT_DB) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame(columns=[
            "market", "last_run", "regime", "symbols_scanned", "trades_today", "status", "error"
        ])
    c = _conn(db_path)
    df = pd.read_sql_query("SELECT * FROM engine_status", c)
    c.close()
    return df
