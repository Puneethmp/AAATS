"""κ2 tape loader — read v5 SQLite `crypto_bars` in deterministic order.

Read-only on the source DB (sqlite3 URI mode=ro). Pure compute; no side
effects. Iteration order is FIXED: `(symbol ASC, timeframe ASC, timestamp ASC)`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    timeframe: str
    timestamp: datetime   # tz-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


def _open_ro(db_path: str | Path) -> sqlite3.Connection:
    """Open SQLite in read-only mode via URI. No mutation possible."""
    p = Path(db_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"tape source not found: {p}")
    uri = f"file:{p.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True, isolation_level=None)


def get_tape_summary(db_path: str | Path) -> dict:
    """Read-only summary of the tape. Used to preview before capture."""
    with _open_ro(db_path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='crypto_bars'"
        ).fetchone()
        if row is None:
            raise RuntimeError(f"crypto_bars table not present in {db_path}")
        total = int(conn.execute("SELECT count(*) FROM crypto_bars").fetchone()[0])
        symbols = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM crypto_bars ORDER BY symbol"
            ).fetchall()
        ]
        timeframes = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT timeframe FROM crypto_bars ORDER BY timeframe"
            ).fetchall()
        ]
        ts_min, ts_max = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM crypto_bars"
        ).fetchone()
        # Per-(symbol, timeframe) row counts — for the operator preview
        per_pair = conn.execute(
            """
            SELECT symbol, timeframe, count(*) AS n,
                   MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts
              FROM crypto_bars
             GROUP BY symbol, timeframe
             ORDER BY symbol, timeframe
            """
        ).fetchall()
    return {
        "db_path": str(db_path),
        "row_count": total,
        "symbol_count": len(symbols),
        "symbols": symbols,
        "timeframes": timeframes,
        "time_min": ts_min,
        "time_max": ts_max,
        "per_pair": [
            {"symbol": s, "timeframe": tf, "rows": int(n),
             "time_min": tmin, "time_max": tmax}
            for s, tf, n, tmin, tmax in per_pair
        ],
    }


def iterate_tape(
    db_path: str | Path,
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: Optional[int] = None,
) -> Iterator[Bar]:
    """Yield Bar objects in deterministic order: (symbol, timeframe, timestamp)."""
    with _open_ro(db_path) as conn:
        clauses, params = [], []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if timeframe is not None:
            clauses.append("timeframe = ?")
            params.append(timeframe)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
        sql = f"""
            SELECT symbol, timeframe, timestamp,
                   open, high, low, close, volume
              FROM crypto_bars
              {where}
             ORDER BY symbol ASC, timeframe ASC, timestamp ASC
             {limit_clause}
        """
        for sym, tf, ts_str, o, h, l, c, v in conn.execute(sql, params):
            yield Bar(
                symbol=sym,
                timeframe=tf,
                timestamp=_parse_iso(ts_str),
                open=float(o), high=float(h), low=float(l),
                close=float(c), volume=float(v),
            )


def _parse_iso(s: str) -> datetime:
    """v5 stores timestamps as ISO8601 UTC strings. Defensive about Z suffix."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
