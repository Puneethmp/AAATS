"""
US market storage layer.

Persists OHLCV and feature DataFrames to a SQLite database via SQLAlchemy.
Tables: us_ohlcv, us_features. PK: (symbol, timestamp). Upsert via INSERT OR REPLACE.
Timestamps stored as UTC ISO-8601 strings for portable lexicographic ordering.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import Column, Float, MetaData, String, Table, create_engine, text
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.engine import Engine

from foundation.logger import get_logger

_log = get_logger(market="us", module="storage")

_MARKET = "us"
_metadata = MetaData()

_us_ohlcv = Table(
    "us_ohlcv",
    _metadata,
    Column("symbol", String, primary_key=True),
    Column("timestamp", String, primary_key=True),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("volume", Float, nullable=False),
    Column("market", String, nullable=False),
)

_us_features = Table(
    "us_features",
    _metadata,
    Column("symbol", String, primary_key=True),
    Column("timestamp", String, primary_key=True),
    Column("return_1d", Float),
    Column("return_5d", Float),
    Column("return_20d", Float),
    Column("return_60d", Float),
    Column("rsi_14", Float),
    Column("macd", Float),
    Column("signal", Float),
    Column("hist", Float),
    Column("ema_20", Float),
    Column("ema_50", Float),
    Column("ema_200", Float),
    Column("bb_upper", Float),
    Column("bb_mid", Float),
    Column("bb_lower", Float),
    Column("adx_14", Float),
    Column("atr_14", Float),
    Column("hist_vol_20", Float),
    Column("obv", Float),
    Column("vol_ratio_20", Float),
    Column("market", String, nullable=False),
)

_OHLCV_STORE_COLS = [
    "symbol",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "market",
]

_FEATURE_STORE_COLS = [
    "symbol",
    "timestamp",
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "rsi_14",
    "macd",
    "signal",
    "hist",
    "ema_20",
    "ema_50",
    "ema_200",
    "bb_upper",
    "bb_mid",
    "bb_lower",
    "adx_14",
    "atr_14",
    "hist_vol_20",
    "obv",
    "vol_ratio_20",
    "market",
]


def get_engine(db_path: str | Path) -> Engine:
    """
    Return a SQLAlchemy engine connected to the SQLite database at db_path.
    Creates the database file if it does not exist.

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        Configured SQLAlchemy Engine.
    """
    url = f"sqlite:///{Path(db_path).resolve()}"
    _log.info(f"Connecting to SQLite — path={db_path}")
    return create_engine(url)


def create_tables(engine: Engine) -> None:
    """
    Create us_ohlcv and us_features tables if they do not already exist.
    Safe to call on every startup (idempotent).

    Args:
        engine: SQLAlchemy Engine targeting the US database.
    """
    _log.info("Creating US storage tables (CREATE IF NOT EXISTS)")
    _metadata.create_all(engine)


def store_ohlcv(engine: Engine, symbol: str, df: pd.DataFrame) -> int:
    """
    Upsert OHLCV rows into us_ohlcv. Existing (symbol, timestamp) pairs are replaced.

    Args:
        engine: SQLAlchemy Engine.
        symbol: Ticker symbol (e.g. "AAPL").
        df:     DataFrame with columns [timestamp, open, high, low, close, volume].
                timestamp must be UTC-aware or naive (treated as UTC).

    Returns:
        Number of rows written.

    Raises:
        ValueError: If any required column is missing from df.
    """
    _check_cols(
        df, {"timestamp", "open", "high", "low", "close", "volume"}, "store_ohlcv"
    )
    if df.empty:
        _log.warning(f"store_ohlcv called with empty DataFrame — symbol={symbol}")
        return 0

    work = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    work["symbol"] = symbol
    work["market"] = _MARKET
    work["timestamp"] = work["timestamp"].apply(_to_utc_iso)
    rows = work[_OHLCV_STORE_COLS].to_dict(orient="records")

    try:
        _upsert(_us_ohlcv, engine, rows)
    except Exception:
        _log.exception(f"store_ohlcv failed — symbol={symbol}")
        raise

    _log.info(f"Stored {len(rows)} OHLCV rows — symbol={symbol}")
    return len(rows)


def store_features(engine: Engine, symbol: str, df: pd.DataFrame) -> int:
    """
    Upsert feature rows into us_features. Existing (symbol, timestamp) pairs are replaced.

    Args:
        engine: SQLAlchemy Engine.
        symbol: Ticker symbol.
        df:     DataFrame output of calculate_features() — must contain 'timestamp'.
                Feature columns absent from df are stored as NULL.

    Returns:
        Number of rows written.

    Raises:
        ValueError: If the timestamp column is missing from df.
    """
    _check_cols(df, {"timestamp"}, "store_features")
    if df.empty:
        _log.warning(f"store_features called with empty DataFrame — symbol={symbol}")
        return 0

    work = df.copy()
    work["symbol"] = symbol
    work["market"] = _MARKET
    work["timestamp"] = work["timestamp"].apply(_to_utc_iso)

    for col in _FEATURE_STORE_COLS:
        if col not in work.columns:
            work[col] = None

    rows = work[_FEATURE_STORE_COLS].to_dict(orient="records")

    try:
        _upsert(_us_features, engine, rows)
    except Exception:
        _log.exception(f"store_features failed — symbol={symbol}")
        raise

    _log.info(f"Stored {len(rows)} feature rows — symbol={symbol}")
    return len(rows)


def query_ohlcv(
    engine: Engine,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """
    Return OHLCV bars for symbol where start <= timestamp <= end (inclusive).
    Rows are ordered ascending by timestamp.

    Args:
        engine: SQLAlchemy Engine.
        symbol: Ticker symbol.
        start:  Query window start (UTC).
        end:    Query window end (UTC).

    Returns:
        DataFrame with OHLCV columns and market column.
        Empty DataFrame (no columns) if no rows match.
    """
    sql = text(
        "SELECT symbol, timestamp, open, high, low, close, volume, market "
        "FROM us_ohlcv "
        "WHERE symbol = :symbol AND timestamp >= :start AND timestamp <= :end "
        "ORDER BY timestamp ASC"
    )
    return _run_query(engine, sql, symbol, start, end)


def query_features(
    engine: Engine,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """
    Return feature rows for symbol where start <= timestamp <= end (inclusive).
    Rows are ordered ascending by timestamp.

    Args:
        engine: SQLAlchemy Engine.
        symbol: Ticker symbol.
        start:  Query window start (UTC).
        end:    Query window end (UTC).

    Returns:
        DataFrame with all feature columns and market column.
        Empty DataFrame (no columns) if no rows match.
    """
    sql = text(
        "SELECT * FROM us_features "
        "WHERE symbol = :symbol AND timestamp >= :start AND timestamp <= :end "
        "ORDER BY timestamp ASC"
    )
    return _run_query(engine, sql, symbol, start, end)


# ── Private helpers ────────────────────────────────────────────────────────────


def _check_cols(df: pd.DataFrame, required: set[str], caller: str) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{caller}: missing required columns {sorted(missing)}")


def _to_utc_iso(ts: Any) -> str:
    """Convert any timestamp-like value to a UTC ISO-8601 string for SQLite storage."""
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.isoformat()


def _upsert(table: Table, engine: Engine, rows: list[dict[str, Any]]) -> None:
    with engine.begin() as conn:
        stmt = _sqlite_insert(table).prefix_with("OR REPLACE")
        conn.execute(stmt, rows)


def _run_query(
    engine: Engine,
    sql: Any,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    params = {
        "symbol": symbol,
        "start": _to_utc_iso(start),
        "end": _to_utc_iso(end),
    }
    try:
        with engine.connect() as conn:
            result = conn.execute(sql, params)
            rows = result.fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows, columns=list(result.keys()))
    except Exception:
        _log.exception(f"Query failed — symbol={symbol}")
        raise
