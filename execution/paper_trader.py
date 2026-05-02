"""
Paper trade executor — writes simulated trades to data/paper_trades.db.

The Streamlit dashboard reads this DB via data_layer.py. This module is the
sole writer; the web app never writes here.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from foundation.logger import get_logger

_log = get_logger("execution", "paper_trader")

Action = Literal["BUY", "SELL"]

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    market      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    action      TEXT NOT NULL,
    shares      REAL NOT NULL,
    price       REAL NOT NULL,
    value       REAL NOT NULL,
    signal      TEXT,
    regime      TEXT,
    risk_action TEXT,
    pnl         REAL DEFAULT 0.0,
    note        TEXT
)
"""


def _conn(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(_CREATE_SQL)
    c.commit()
    return c


def record_trade(
    db_path: str,
    market: str,
    symbol: str,
    action: Action,
    shares: float,
    price: float,
    signal: str = "",
    regime: str = "",
    risk_action: str = "ALLOW",
    pnl: float = 0.0,
    note: str = "",
) -> str:
    """Insert one paper trade row. Returns the generated trade id."""
    trade_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    value = round(shares * price, 4)

    c = _conn(db_path)
    c.execute(
        "INSERT INTO paper_trades "
        "(id,timestamp,market,symbol,action,shares,price,value,signal,regime,risk_action,pnl,note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (trade_id, ts, market, symbol, action, shares, price, value,
         signal, regime, risk_action, pnl, note),
    )
    c.commit()
    c.close()
    _log.info(f"PAPER {action} {symbol} @ {price:.4f} x{shares} | {signal} | {regime}")
    return trade_id
