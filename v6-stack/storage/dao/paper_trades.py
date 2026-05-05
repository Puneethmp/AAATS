"""DAO for aaats.paper_trades — append-only.

Mirrors v5's `paper_trades.db::paper_trades` schema for parity. UUID `id`
preserved (v5 wrote string UUIDs).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .. import audit, postgres as _pg


async def record(
    *,
    id: str,
    timestamp: datetime,
    market: str,
    symbol: str,
    action: str,
    shares: float,
    price: float,
    value: float,
    signal: Optional[str] = None,
    regime: Optional[str] = None,
    risk_action: Optional[str] = None,
    pnl: Optional[float] = None,
    note: Optional[str] = None,
) -> None:
    if action not in ("BUY", "SELL"):
        raise ValueError(f"action must be BUY|SELL, got {action!r}")
    async with _pg.transaction(label="paper_trades.record") as conn:
        await conn.execute(
            """
            INSERT INTO aaats.paper_trades
                (id, timestamp, market, symbol, action, shares, price, value,
                 signal, regime, risk_action, pnl, note)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            """,
            id, timestamp, market, symbol, action,
            float(shares), float(price), float(value),
            signal, regime, risk_action, pnl, note,
        )
        audit.track_affected_rows(conn, 1)


async def count(market: Optional[str] = None) -> int:
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        if market is None:
            row = await conn.fetchrow("SELECT count(*) AS n FROM aaats.paper_trades")
        else:
            row = await conn.fetchrow(
                "SELECT count(*) AS n FROM aaats.paper_trades WHERE market=$1", market,
            )
    return int(row["n"])
