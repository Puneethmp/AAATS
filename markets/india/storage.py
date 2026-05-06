"""
India market storage layer.

Persists equity bars and F&O option chain snapshots to SQLite via SQLAlchemy.
Tables:
  india_equity_bars — PK: (symbol, timestamp)
  india_fo_bars     — PK: (symbol, expiry, strike, option_type, timestamp)

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

_log = get_logger(market="india", module="storage")

_metadata = MetaData()

_india_equity_bars = Table(
    "india_equity_bars",
    _metadata,
    Column("symbol", String, primary_key=True),
    Column("timestamp", String, primary_key=True),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("volume", Float, nullable=False),
    Column("atr_14", Float),
)

_india_fo_bars = Table(
    "india_fo_bars",
    _metadata,
    Column("symbol", String, primary_key=True),
    Column("expiry", String, primary_key=True),
    Column("strike", Float, primary_key=True),
    Column("option_type", String, primary_key=True),
    Column("timestamp", String, primary_key=True),
    Column("open", Float),
    Column("high", Float),
    Column("low", Float),
    Column("close", Float),
    Column("volume", Float),
    Column("oi", Float),
    Column("iv", Float),
)

_BARS_REQUIRED = {"timestamp", "open", "high", "low", "close", "volume"}
_FO_REQUIRED = {"strike", "option_type"}

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


def _upsert(table: Table, engine: Engine, rows: list[dict[str, Any]]) -> None:
    with engine.begin() as conn:
        stmt = _sqlite_insert(table).prefix_with("OR REPLACE")
        conn.execute(stmt, rows)


def store_bars(df: pd.DataFrame, symbol: str, db_path: str) -> int:
    """
    Upsert equity bars into india_equity_bars. Duplicate (symbol, timestamp) is replaced.

    Args:
        df:      DataFrame with columns [timestamp, open, high, low, close, volume].
                 atr_14 is optional — stored as NULL if absent.
        symbol:  NSE/BSE ticker (e.g. "RELIANCE").
        db_path: Path to SQLite database file.

    Returns:
        Number of rows written.
    """
    _check_cols(df, _BARS_REQUIRED, "store_bars")
    if df.empty:
        _log.warning(f"store_bars called with empty DataFrame — symbol={symbol}")
        return 0

    engine = _get_engine(db_path)
    _ensure_tables(engine)

    work = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    work["symbol"] = symbol
    work["atr_14"] = df["atr_14"].values if "atr_14" in df.columns else None
    work["timestamp"] = work["timestamp"].apply(_to_utc_iso)

    store_cols = ["symbol", "timestamp", "open", "high", "low", "close", "volume", "atr_14"]
    rows = work[store_cols].to_dict(orient="records")

    try:
        _upsert(_india_equity_bars, engine, rows)
    except Exception:
        _log.exception(f"store_bars failed — symbol={symbol}")
        raise

    _log.info(f"Stored {len(rows)} equity bars — symbol={symbol}")
    return len(rows)


def fetch_bars(symbol: str, start: str, end: str, db_path: str) -> pd.DataFrame:
    """
    Return equity bars for symbol where start <= timestamp <= end (inclusive).

    Args:
        symbol:  NSE/BSE ticker.
        start:   ISO-8601 start timestamp (inclusive).
        end:     ISO-8601 end timestamp (inclusive).
        db_path: Path to SQLite database file.

    Returns:
        DataFrame ordered by timestamp ascending. Empty DataFrame if no rows match.
    """
    engine = _get_engine(db_path)
    _ensure_tables(engine)

    start_iso = _to_utc_iso(start)
    end_iso = _to_utc_iso(end)

    sql = text(
        "SELECT symbol, timestamp, open, high, low, close, volume, atr_14 "
        "FROM india_equity_bars "
        "WHERE symbol = :symbol AND timestamp >= :start AND timestamp <= :end "
        "ORDER BY timestamp ASC"
    )
    try:
        with engine.connect() as conn:
            result = conn.execute(sql, {"symbol": symbol, "start": start_iso, "end": end_iso})
            rows = result.fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows, columns=list(result.keys()))
    except Exception:
        _log.exception(f"fetch_bars failed — symbol={symbol}")
        raise


def store_option_chain_snapshot(
    df: pd.DataFrame,
    underlying: str,
    timestamp: str,
    db_path: str,
) -> int:
    """
    Store an option chain snapshot into india_fo_bars.

    Args:
        df:         DataFrame with at minimum [strike, option_type].
                    Optional: expiry, open, high, low, close, ltp, volume, oi, iv.
                    If close absent, falls back to ltp. If neither present, stores NULL.
        underlying: Index or stock name (e.g. "NIFTY"). Stored as symbol.
        timestamp:  Snapshot timestamp (ISO-8601 or pd.Timestamp).
        db_path:    Path to SQLite database file.

    Returns:
        Number of rows written.
    """
    _check_cols(df, _FO_REQUIRED, "store_option_chain_snapshot")
    if df.empty:
        _log.warning(
            f"store_option_chain_snapshot called with empty DataFrame — underlying={underlying}"
        )
        return 0

    engine = _get_engine(db_path)
    _ensure_tables(engine)

    ts_iso = _to_utc_iso(timestamp)
    work = df.copy()
    work["symbol"] = underlying
    work["timestamp"] = ts_iso

    if "expiry" not in work.columns:
        work["expiry"] = ""

    # Resolve price columns
    if "close" not in work.columns:
        work["close"] = work["ltp"] if "ltp" in work.columns else None
    for col in ("open", "high", "low"):
        if col not in work.columns:
            work[col] = work["close"]

    for col in ("volume", "oi", "iv"):
        if col not in work.columns:
            work[col] = None

    store_cols = [
        "symbol", "expiry", "strike", "option_type", "timestamp",
        "open", "high", "low", "close", "volume", "oi", "iv",
    ]
    rows = work[store_cols].to_dict(orient="records")

    try:
        _upsert(_india_fo_bars, engine, rows)
    except Exception:
        _log.exception(f"store_option_chain_snapshot failed — underlying={underlying}")
        raise

    _log.info(
        f"Stored {len(rows)} F&O snapshot rows — underlying={underlying}, ts={ts_iso}"
    )
    return len(rows)


def fetch_option_chain_history(
    underlying: str,
    start: str,
    end: str,
    db_path: str,
) -> pd.DataFrame:
    """
    Return option chain snapshots for underlying where start <= timestamp <= end (inclusive).

    Args:
        underlying: Index or stock name matching the symbol column.
        start:      ISO-8601 start timestamp (inclusive).
        end:        ISO-8601 end timestamp (inclusive).
        db_path:    Path to SQLite database file.

    Returns:
        DataFrame ordered by (timestamp, strike, option_type). Empty DataFrame if no rows.
    """
    engine = _get_engine(db_path)
    _ensure_tables(engine)

    start_iso = _to_utc_iso(start)
    end_iso = _to_utc_iso(end)

    sql = text(
        "SELECT symbol, expiry, strike, option_type, timestamp, "
        "open, high, low, close, volume, oi, iv "
        "FROM india_fo_bars "
        "WHERE symbol = :symbol AND timestamp >= :start AND timestamp <= :end "
        "ORDER BY timestamp ASC, strike ASC, option_type ASC"
    )
    try:
        with engine.connect() as conn:
            result = conn.execute(sql, {"symbol": underlying, "start": start_iso, "end": end_iso})
            rows = result.fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows, columns=list(result.keys()))
    except Exception:
        _log.exception(f"fetch_option_chain_history failed — underlying={underlying}")
        raise
