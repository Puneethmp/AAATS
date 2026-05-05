"""DAO for halt state.

Two stores:
  - aaats.halt_audit (Postgres) — DURABLE TRUTH (CST). Risk decisions consult.
  - Redis aaats:halt:requested  — fast cache (FAD §4.5 / Phase ζ).

Per κ1 req 11: risk-critical paths must read from Postgres only.
The Redis key is for the bot / dashboards / non-risk reads.

Per κ1 req 10: no automatic remediation here. Halt and reset both append a
row; the operator (or operator-equivalent caller) is responsible for the
content.
"""

from __future__ import annotations

from typing import Optional

from .. import audit, postgres as _pg, redis as _redis


# =============================================================================
# Durable / risk-safe path (Postgres)
# =============================================================================

async def append_halt_event(
    *,
    market: str,
    action: str,                   # 'halt' | 'reset'
    triggered_by: str,
    reason: str,
    authorized_by: Optional[str] = None,
) -> int:
    if action not in ("halt", "reset"):
        raise ValueError(f"action must be 'halt' or 'reset', got {action!r}")
    async with _pg.transaction(label=f"halt.{action}") as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO aaats.halt_audit
                (market, action, triggered_by, reason, authorized_by)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            market, action, triggered_by, reason, authorized_by,
        )
        audit.track_affected_rows(conn, 1)
        return int(row["id"])


async def read_durable_current_state(market: str) -> dict:
    """Risk-critical halt-state read.

    Returns {'halted': bool, 'last_event': {...}|None}. Walks the audit table
    backwards to find the most recent halt or reset for the market.

    THIS FUNCTION IS THE ONE risk/engine.py CALLS. Never short-circuits via
    Redis cache (κ1 req 11).
    """
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, timestamp, market, action, triggered_by, reason, authorized_by
              FROM aaats.halt_audit
             WHERE market = $1 OR market = 'all'
             ORDER BY id DESC
             LIMIT 1
            """,
            market,
        )
    if row is None:
        return {"halted": False, "last_event": None}
    return {
        "halted": row["action"] == "halt",
        "last_event": dict(row),
    }


# =============================================================================
# Cache helpers (Redis) — for the bot / dashboards. NOT for risk reads.
# =============================================================================

async def cache_set_request(payload: str, ex_seconds: int = 86400) -> None:
    """Set the live `aaats:halt:requested` Redis key. Used by Phase ζ /pause
    and /kill commands. Cache only — DOES NOT write to Postgres. Caller
    should also call append_halt_event() for the durable record.
    """
    r = _redis.get_redis()
    await r.set(_redis.KEYS.HALT_REQUESTED, payload, ex=ex_seconds)


async def cache_clear_request() -> int:
    r = _redis.get_redis()
    return int(await r.delete(_redis.KEYS.HALT_REQUESTED))


async def cache_read_request() -> Optional[str]:
    r = _redis.get_redis()
    val = await r.get(_redis.KEYS.HALT_REQUESTED)
    return val.decode("utf-8") if val is not None else None
