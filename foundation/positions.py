"""foundation/positions.py  —  Unified positions ledger (Q1=A, Q3=A).

Single source of truth for open positions, stored as a ``positions`` table in
``data/paper_trades.db`` alongside ``paper_trades``. Replaces the
N-source-of-truth problem caused by per-strategy ``*_state.json`` files.

Spec: docs/specs/unified_positions_ledger.md
Decisions: docs/decisions/2026-05-21_ledger_spec_recommendations.md

Public API
----------
    open_position(strategy, symbol, market, entry_shares, entry_price,
                  size_usd, entry_ts, correlation_id=None, metadata=None,
                  db_path=None) -> None
    close_position(strategy, symbol, db_path=None) -> dict | None
    get_position(strategy, symbol, db_path=None) -> dict | None
    list_positions(strategy=None, market=None, db_path=None) -> list[dict]

Schema
------
    PRIMARY KEY (strategy, symbol)  -- two strategies may hold same symbol.
    metadata_json: opaque TEXT (Q3=A). Pydantic validates the dict shape at
                   the API boundary; SQLite stores the JSON-serialized form.

This module is import-safe. It has no global state and creates the table
lazily on first call via ``CREATE TABLE IF NOT EXISTS``. Strategy code does
NOT call this module until workstream B3 wires it behind ``USE_UNIFIED_LEDGER``.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DEFAULT_DB_PATH = str(_ROOT / "data" / "paper_trades.db")

_CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS positions ("
    "strategy             TEXT NOT NULL,"
    "symbol               TEXT NOT NULL,"
    "market               TEXT NOT NULL,"
    "entry_shares         REAL NOT NULL,"
    "entry_price          REAL NOT NULL,"
    "size_usd             REAL NOT NULL,"
    "entry_ts             TEXT NOT NULL,"
    "entry_correlation_id TEXT,"
    "metadata_json        TEXT,"
    "PRIMARY KEY (strategy, symbol)"
    ")"
)

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_positions_market ON positions(market)"
)

_SELECT_COLS = (
    "strategy, symbol, market, entry_shares, entry_price, size_usd, "
    "entry_ts, entry_correlation_id, metadata_json"
)


class _PositionInput(BaseModel):
    """Pydantic boundary validator for ``open_position`` (Q3=A typing gate)."""

    model_config = ConfigDict(extra="forbid")
    strategy: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    market: str = Field(min_length=1)
    entry_shares: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    size_usd: float = Field(gt=0)
    entry_ts: str = Field(min_length=1)
    entry_correlation_id: str | None = None
    metadata: dict[str, Any] | None = None


def _conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or _DEFAULT_DB_PATH
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(_CREATE_SQL)
    c.execute(_INDEX_SQL)
    c.commit()
    return c


def _row_to_dict(row: tuple) -> dict[str, Any]:
    (strategy, symbol, market, entry_shares, entry_price, size_usd,
     entry_ts, cid, meta) = row
    return {
        "strategy": strategy,
        "symbol": symbol,
        "market": market,
        "entry_shares": entry_shares,
        "entry_price": entry_price,
        "size_usd": size_usd,
        "entry_ts": entry_ts,
        "entry_correlation_id": cid,
        "metadata": json.loads(meta) if meta else None,
    }


def open_position(
    strategy: str,
    symbol: str,
    market: str,
    entry_shares: float,
    entry_price: float,
    size_usd: float,
    entry_ts: str,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> None:
    """Insert a new open position.

    Raises ``sqlite3.IntegrityError`` if a row with the same
    ``(strategy, symbol)`` already exists — callers must close the prior
    position first.
    """
    v = _PositionInput(
        strategy=strategy,
        symbol=symbol,
        market=market,
        entry_shares=entry_shares,
        entry_price=entry_price,
        size_usd=size_usd,
        entry_ts=entry_ts,
        entry_correlation_id=correlation_id,
        metadata=metadata,
    )
    meta_json = json.dumps(v.metadata) if v.metadata is not None else None
    with _conn(db_path) as c:
        c.execute(
            "INSERT INTO positions ("
            "strategy, symbol, market, entry_shares, entry_price, "
            "size_usd, entry_ts, entry_correlation_id, metadata_json"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                v.strategy, v.symbol, v.market, v.entry_shares, v.entry_price,
                v.size_usd, v.entry_ts, v.entry_correlation_id, meta_json,
            ),
        )


def get_position(
    strategy: str, symbol: str, db_path: str | None = None
) -> dict[str, Any] | None:
    with _conn(db_path) as c:
        row = c.execute(
            f"SELECT {_SELECT_COLS} FROM positions "
            "WHERE strategy=? AND symbol=?",
            (strategy, symbol),
        ).fetchone()
    return _row_to_dict(row) if row else None


def close_position(
    strategy: str, symbol: str, db_path: str | None = None
) -> dict[str, Any] | None:
    """Atomic SELECT + DELETE. Returns the deleted row or ``None`` if absent."""
    with _conn(db_path) as c:
        row = c.execute(
            f"SELECT {_SELECT_COLS} FROM positions "
            "WHERE strategy=? AND symbol=?",
            (strategy, symbol),
        ).fetchone()
        if row is None:
            return None
        c.execute(
            "DELETE FROM positions WHERE strategy=? AND symbol=?",
            (strategy, symbol),
        )
    return _row_to_dict(row)


def list_positions(
    strategy: str | None = None,
    market: str | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    query = f"SELECT {_SELECT_COLS} FROM positions"
    where: list[str] = []
    params: list[Any] = []
    if strategy is not None:
        where.append("strategy=?")
        params.append(strategy)
    if market is not None:
        where.append("market=?")
        params.append(market)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY strategy, symbol"
    with _conn(db_path) as c:
        rows = c.execute(query, tuple(params)).fetchall()
    return [_row_to_dict(r) for r in rows]
