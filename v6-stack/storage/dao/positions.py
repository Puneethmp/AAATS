"""DAO for aaats.positions.

Exposes BOTH `read_durable_*` (Postgres) and `read_cached_*` (Redis)
read paths. Per κ1 req 11, only `read_durable_*` is acceptable on the
risk decision path.

`open_position()` and `close_position()` are the only sanctioned writers.
The schema enforces the open-vs-closed consistency CHECK constraint and a
unique-when-open partial index on (market, symbol).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

import asyncpg

from .. import audit, postgres as _pg, redis as _redis


class DuplicateOpenPositionError(Exception):
    """Raised when an open position already exists for (market, symbol)."""


async def open_position(
    *,
    market: str,
    symbol: str,
    entry_price: float,
    shares: float,
    entry_time: datetime,
    metadata: Optional[dict] = None,
) -> int:
    md = metadata or {}
    try:
        async with _pg.transaction(label="positions.open") as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO aaats.positions
                    (symbol, market, entry_price, shares, entry_time, metadata, closed)
                VALUES ($1,$2,$3,$4,$5,$6, FALSE)
                RETURNING id
                """,
                symbol, market, float(entry_price), float(shares), entry_time, md,
            )
            audit.track_affected_rows(conn, 1)
            return int(row["id"])
    except asyncpg.exceptions.UniqueViolationError as e:
        raise DuplicateOpenPositionError(
            f"open position for ({market}, {symbol}) already exists"
        ) from e


async def close_position(
    position_id: int,
    *,
    exit_price: float,
    exit_time: datetime,
    pnl: float,
) -> None:
    """Close an open position. Idempotency is via the consistency CHECK in the
    schema: attempting to close an already-closed row will fail validation.
    """
    async with _pg.transaction(label="positions.close") as conn:
        result = await conn.execute(
            """
            UPDATE aaats.positions
               SET closed     = TRUE,
                   exit_price = $2,
                   exit_time  = $3,
                   pnl        = $4
             WHERE id = $1 AND closed = FALSE
            """,
            position_id, float(exit_price), exit_time, float(pnl),
        )
        # asyncpg returns a string like "UPDATE 1"
        affected = int((result or "UPDATE 0").split()[-1])
        if affected == 0:
            raise ValueError(f"position id={position_id} not found or already closed")
        audit.track_affected_rows(conn, affected)


# =============================================================================
# DURABLE READS (Postgres) — risk-safe path (κ1 req 11)
# =============================================================================

async def read_durable_open(market: str) -> list[dict[str, Any]]:
    """Risk-safe: open positions in a market."""
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM aaats.positions WHERE market=$1 AND closed=FALSE ORDER BY id ASC",
            market,
        )
    return [dict(r) for r in rows]


async def read_durable_by_symbol(market: str, symbol: str) -> Optional[dict[str, Any]]:
    """Risk-safe: open position for (market, symbol). Returns None if none."""
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM aaats.positions WHERE market=$1 AND symbol=$2 AND closed=FALSE",
            market, symbol,
        )
    return None if row is None else dict(row)


# =============================================================================
# CACHED READS (Redis) — DASHBOARDS / BOT ONLY. NEVER on risk path.
# =============================================================================

async def read_cached_open(market: str) -> Optional[list[dict[str, Any]]]:
    """⚠️  NOT risk-safe.  Cache may be stale. For dashboards / bot only."""
    r = _redis.get_redis()
    raw = await r.get(_redis.KEYS.CACHE_POSITIONS_FOR.format(market=market))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def cache_open_positions(market: str, ttl_s: int = 5) -> None:
    """Refresh the cache from Postgres. Call from a perimeter (dashboard
    refresher, status command); never on the risk hot path.
    """
    rows = await read_durable_open(market)
    # Convert datetimes to ISO for JSON safety.
    clean = []
    for row in rows:
        d = dict(row)
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        clean.append(d)
    r = _redis.get_redis()
    await r.set(
        _redis.KEYS.CACHE_POSITIONS_FOR.format(market=market),
        json.dumps(clean, default=str),
        ex=int(ttl_s),
    )
