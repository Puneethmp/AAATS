"""DAO for aaats.engine_status — per-market upserts.

Mirrors v5's `status.db::engine_status` shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .. import audit, postgres as _pg


async def upsert(
    *,
    market: str,
    last_run: datetime,
    status: str,
    regime: Optional[str] = None,
    symbols_scanned: int = 0,
    trades_today: int = 0,
    error: Optional[str] = None,
    heartbeat_ts: Optional[datetime] = None,
    cycle_count: int = 0,
) -> None:
    async with _pg.transaction(label="engine_status.upsert") as conn:
        await conn.execute(
            """
            INSERT INTO aaats.engine_status
                (market, last_run, regime, symbols_scanned, trades_today,
                 status, error, heartbeat_ts, cycle_count)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (market) DO UPDATE SET
                last_run        = EXCLUDED.last_run,
                regime          = EXCLUDED.regime,
                symbols_scanned = EXCLUDED.symbols_scanned,
                trades_today    = EXCLUDED.trades_today,
                status          = EXCLUDED.status,
                error           = EXCLUDED.error,
                heartbeat_ts    = EXCLUDED.heartbeat_ts,
                cycle_count     = EXCLUDED.cycle_count
            """,
            market, last_run, regime, int(symbols_scanned), int(trades_today),
            status, error, heartbeat_ts, int(cycle_count),
        )
        audit.track_affected_rows(conn, 1)


async def read(market: str) -> Optional[dict]:
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM aaats.engine_status WHERE market=$1", market)
    return None if row is None else dict(row)
