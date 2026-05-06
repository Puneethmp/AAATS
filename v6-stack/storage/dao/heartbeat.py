"""DAO for engine + watchdog heartbeats.

These are EPHEMERAL by design — Redis is the canonical store; loss after a
TTL window is acceptable. NOT to be confused with `aaats.engine_status`
(durable per-cycle status) or `aaats.tx_audit` (durable per-tx audit).
"""

from __future__ import annotations

from typing import Optional

from .. import redis as _redis
from ..clock import utc_now_ts


HB_TTL_S = 90       # FAD §4.2: HB write every 30s, TTL 90s


async def emit_engine(cycle_id: int, status: str = "OK", market: Optional[str] = None) -> None:
    r = _redis.get_redis()
    val = f"{utc_now_ts():.3f}:{cycle_id}:{status}"
    await r.set(_redis.KEYS.HB_ENGINE, val, ex=HB_TTL_S)
    if market:
        await r.set(_redis.KEYS.HB_ENGINE_FOR.format(market=market), val, ex=HB_TTL_S)


async def emit_watchdog(status: str = "ALIVE") -> None:
    r = _redis.get_redis()
    await r.set(_redis.KEYS.HB_WATCHDOG, f"{utc_now_ts():.3f}:{status}", ex=HB_TTL_S)


async def read_engine() -> Optional[str]:
    r = _redis.get_redis()
    val = await r.get(_redis.KEYS.HB_ENGINE)
    return val.decode("utf-8") if val is not None else None


async def read_watchdog() -> Optional[str]:
    r = _redis.get_redis()
    val = await r.get(_redis.KEYS.HB_WATCHDOG)
    return val.decode("utf-8") if val is not None else None
