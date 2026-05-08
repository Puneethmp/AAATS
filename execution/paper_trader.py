"""
Paper trade executor — writes simulated trades to data/paper_trades.db.

The Streamlit dashboard reads this DB via data_layer.py. This module is the
sole writer; the web app never writes here.

Schema v2 additions (2026-05-08):
  strategy   -- AAATS strategy ID (e.g. "C1_stat_arb", "C2_momentum", "C5b_funding_arb")
  entry_time -- ISO timestamp of position open (same as timestamp for BUY rows)
  exit_time  -- ISO timestamp of position close (NULL for open positions)
  pnl_pct    -- percentage PnL at close (NULL for open positions)
  notes      -- JSON blob: confidence, exit_reason, r_multiple, size_usd, skipped_regime
  size_usd   -- notional value of trade in USD/INR

A trades VIEW aliases paper_trades for the metrics exporter.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from foundation.logger import get_logger

_log = get_logger("execution", "paper_trader")

Action = Literal["BUY", "SELL"]

_CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS paper_trades ("
    "id          TEXT PRIMARY KEY,"
    "timestamp   TEXT NOT NULL,"
    "market      TEXT NOT NULL,"
    "symbol      TEXT NOT NULL,"
    "action      TEXT NOT NULL,"
    "shares      REAL NOT NULL,"
    "price       REAL NOT NULL,"
    "value       REAL NOT NULL,"
    "signal      TEXT,"
    "regime      TEXT,"
    "risk_action TEXT,"
    "pnl         REAL DEFAULT 0.0,"
    "note        TEXT,"
    "strategy    TEXT DEFAULT '',"
    "entry_time  TEXT,"
    "exit_time   TEXT,"
    "pnl_pct     REAL,"
    "notes       TEXT,"
    "size_usd    REAL DEFAULT 0.0"
    ")"
)

_VIEW_SQL = (
    "CREATE VIEW IF NOT EXISTS trades AS "
    "SELECT id, timestamp, market, symbol, action, shares, price, value, "
    "signal, regime, risk_action, pnl, note, "
    "strategy, entry_time, exit_time, pnl_pct, notes, size_usd "
    "FROM paper_trades"
)

# Migration: safely add v2 columns to any existing v1 DB
_MIGRATE_SQLS = [
    "ALTER TABLE paper_trades ADD COLUMN strategy   TEXT    DEFAULT ''",
    "ALTER TABLE paper_trades ADD COLUMN entry_time TEXT",
    "ALTER TABLE paper_trades ADD COLUMN exit_time  TEXT",
    "ALTER TABLE paper_trades ADD COLUMN pnl_pct    REAL",
    "ALTER TABLE paper_trades ADD COLUMN notes      TEXT",
    "ALTER TABLE paper_trades ADD COLUMN size_usd   REAL    DEFAULT 0.0",
]


def _conn(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(_CREATE_SQL)
    for sql in _MIGRATE_SQLS:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    try:
        c.execute("DROP VIEW IF EXISTS trades")
        c.execute(_VIEW_SQL)
    except sqlite3.OperationalError:
        pass
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
    strategy: str = "",
    entry_time: str | None = None,
    exit_time: str | None = None,
    pnl_pct: float | None = None,
    notes: dict[str, Any] | None = None,
    size_usd: float = 0.0,
) -> str:
    """Insert one paper trade row. Returns the generated trade id."""
    trade_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    value = round(shares * price, 4)

    if entry_time is None:
        entry_time = ts if action == "BUY" else None
    if size_usd == 0.0:
        size_usd = round(value, 4)

    notes_json = json.dumps(notes) if notes else None

    c = _conn(db_path)
    c.execute(
        "INSERT INTO paper_trades "
        "(id,timestamp,market,symbol,action,shares,price,value,signal,regime,"
        "risk_action,pnl,note,strategy,entry_time,exit_time,pnl_pct,notes,size_usd) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (trade_id, ts, market, symbol, action, shares, price, value,
         signal, regime, risk_action, pnl, note,
         strategy, entry_time, exit_time, pnl_pct, notes_json, size_usd),
    )
    c.commit()
    c.close()
    _log.info(
        "PAPER %s %s @ %.4f x%.6f | strat=%s | regime=%s",
        action, symbol, price, shares, strategy or signal, regime,
    )
    return trade_id
