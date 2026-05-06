"""DAO for aaats.mode_state — single-row enforcement table."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .. import audit, postgres as _pg, redis as _redis


async def read_durable() -> dict:
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM aaats.mode_state WHERE id = 1")
    if row is None:
        # Should not happen — migration 0001 inserts the seed row. Treat as bug.
        raise RuntimeError("aaats.mode_state seed row missing — schema migration broken")
    return dict(row)


async def switch_mode(*, mode: str, capital: float, authorized_by: str) -> None:
    if mode not in ("paper", "live"):
        raise ValueError(f"mode must be paper|live, got {mode!r}")
    async with _pg.transaction(label=f"mode.switch[{mode}]") as conn:
        if mode == "live":
            await conn.execute(
                """
                UPDATE aaats.mode_state
                   SET mode = 'live',
                       capital = $1,
                       went_live_at = now(),
                       authorized_by = $2,
                       last_updated = now()
                 WHERE id = 1
                """,
                float(capital), authorized_by,
            )
        else:
            await conn.execute(
                """
                UPDATE aaats.mode_state
                   SET mode = 'paper',
                       capital = $1,
                       authorized_by = $2,
                       last_updated = now()
                 WHERE id = 1
                """,
                float(capital), authorized_by,
            )
        audit.track_affected_rows(conn, 1)


async def cache_set(mode: str, ttl_s: int = 60) -> None:
    """Best-effort cache for the bot. Not consulted on the risk path."""
    r = _redis.get_redis()
    await r.set(_redis.KEYS.MODE, mode, ex=ttl_s)
