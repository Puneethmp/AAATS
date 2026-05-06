"""
Crypto market storage layer.

Persists OHLCV bars for crypto pairs to SQLite via SQLAlchemy.
Table:
  crypto_bars — PK: (symbol, timeframe, timestamp)

Timestamps stored as UTC ISO-8601 strings for portable lexicographic ordering.
Engines are cached per resolved db_path to avoid redundant pool creation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Column, Float, MetaData, String, Table, create_engine, text
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.engine import Engine

from foundation.logger import get_logger

_log = get_logger("crypto", "storage")

_metadata = MetaData()

_crypto_bars = Table(
    "crypto_bars",
    _metadata,
    Column("symbol", String, primary_key=True),
    Column("timeframe", String, primary_key=True),
    Column("timestamp", String, primary_key=True),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("volume", Float, nullable=False),
)

_REQUIRED_COLS = {"timestamp", "open", "high", "low", "close", "volume"}

_engine_cache: dict[str, Engine] = {}


def _get_engine(db_path: str | Path) -> Engine:
    key = str(Path(db_path).resolve())
    if key not in _engine_cache:
        _engine_cache[key] = create_engine(f"sqlite:///{key}")
    return _engine_cache[key]


def _ensure_tables(engine: Engine) -> None:
    _metadata.create_all(engine)


def _to_utc_iso(ts: Any) -> str:
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.isoformat()


def _check_cols(df: pd.DataFrame, required: set[str], caller: str) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{caller}: missing required columns {sorted(missing)}")


def _upsert(engine: Engine, rows: list[dict[str, Any]]) -> None:
    with engine.begin() as conn:
        stmt = _sqlite_insert(_crypto_bars).prefix_with("OR REPLACE")
        conn.execute(stmt, rows)


def store_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    db_path: str,
) -> int:
    """
    Upsert crypto OHLCV bars into crypto_bars.

    Duplicate (symbol, timeframe, timestamp) rows are replaced via INSERT OR REPLACE.

    Args:
        df:        DataFrame with columns [timestamp, open, high, low, close, volume].
        symbol:    Exchange market symbol (e.g. "BTC/USDT").
        timeframe: Bar size string (e.g. "1Day", "1Hour").
        db_path:   Path to SQLite database file.

    Returns:
        Number of rows written.
    """
    _check_cols(df, _REQUIRED_COLS, "store_bars")
    if df.empty:
        _log.warning(f"store_bars called with empty DataFrame — symbol={symbol}")
        return 0

    engine = _get_engine(db_path)
    _ensure_tables(engine)

    work = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    work["symbol"] = symbol
    work["timeframe"] = timeframe
    work["timestamp"] = work["timestamp"].apply(_to_utc_iso)

    store_cols = ["symbol", "timeframe", "timestamp", "open", "high", "low", "close", "volume"]
    rows = work[store_cols].to_dict(orient="records")

    try:
        _upsert(engine, rows)
    except Exception:
        _log.exception(f"store_bars failed — symbol={symbol}, timeframe={timeframe}")
        raise

    _log.info(f"Stored {len(rows)} bars — symbol={symbol}, timeframe={timeframe}")
    return len(rows)


def fetch_bars(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    db_path: str,
) -> pd.DataFrame:
    """
    Return crypto bars for symbol/timeframe where start <= timestamp <= end.

    Args:
        symbol:    Exchange market symbol (e.g. "BTC/USDT").
        timeframe: Bar size string (e.g. "1Day", "1Hour").
        start:     ISO-8601 start timestamp (inclusive).
        end:       ISO-8601 end timestamp (inclusive).
        db_path:   Path to SQLite database file.

    Returns:
        DataFrame ordered by timestamp ascending.
        Empty DataFrame if no rows match.
    """
    engine = _get_engine(db_path)
    _ensure_tables(engine)

    start_iso = _to_utc_iso(start)
    end_iso = _to_utc_iso(end)

    sql = text(
        "SELECT symbol, timeframe, timestamp, open, high, low, close, volume "
        "FROM crypto_bars "
        "WHERE symbol = :symbol AND timeframe = :timeframe "
        "  AND timestamp >= :start AND timestamp <= :end "
        "ORDER BY timestamp ASC"
    )
    try:
        with engine.connect() as conn:
            result = conn.execute(
                sql,
                {"symbol": symbol, "timeframe": timeframe, "start": start_iso, "end": end_iso},
            )
            rows = result.fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows, columns=list(result.keys()))
    except Exception:
        _log.exception(f"fetch_bars failed — symbol={symbol}, timeframe={timeframe}")
        raise


def fetch_latest_timestamp(
    symbol: str,
    timeframe: str,
    db_path: str,
) -> str | None:
    """
    Return the most recent stored timestamp for a symbol/timeframe pair.

    Useful for incremental fetching: start the next download from this timestamp.

    Args:
        symbol:    Exchange market symbol.
        timeframe: Bar size string.
        db_path:   Path to SQLite database file.

    Returns:
        ISO-8601 UTC string of the latest timestamp, or None if no rows exist.
    """
    engine = _get_engine(db_path)
    _ensure_tables(engine)

    sql = text(
        "SELECT MAX(timestamp) FROM crypto_bars "
        "WHERE symbol = :symbol AND timeframe = :timeframe"
    )
    with engine.connect() as conn:
        result = conn.execute(sql, {"symbol": symbol, "timeframe": timeframe})
        row = result.fetchone()
        return row[0] if row and row[0] is not None else None
