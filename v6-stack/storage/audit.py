"""Transaction audit utilities.

The bulk of audit logging happens inside `storage.postgres.transaction()`
(see κ1 req 6). This module exposes helpers that callers occasionally need:

  - track_affected_rows(conn, n)         — annotate the current transaction's
                                            tally so it lands in tx_audit.
  - latest_tx_audit_rows(limit=20)       — read-only inspector for shadow
                                            mode dashboards.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from . import postgres as _pg


def track_affected_rows(conn: asyncpg.Connection, n: int) -> None:
    """Add `n` to the current transaction's affected-row counter.

    The counter rides on a `contextvars.ContextVar` defined in
    `storage.postgres` (asyncpg's PoolConnectionProxy refuses setattr, so
    we can't hang the counter on the connection itself). The
    `_affected_rows_ctx` is set/reset by `transaction()`; calling this
    helper outside a transaction context is a no-op.

    The `conn` parameter is kept for API stability — callers already pass
    it. We don't use it.
    """
    from . import postgres as _pg
    try:
        ctx = _pg._affected_rows_ctx.get()
    except LookupError:
        return
    ctx[0] = ctx[0] + int(n)


async def latest_tx_audit_rows(limit: int = 20) -> list[dict[str, Any]]:
    """Inspector for shadow-mode dashboards. NOT on the hot path."""
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, started_at, ended_at, duration_ms, label, status,
                   affected_rows, error_msg, pid
              FROM aaats.tx_audit
             ORDER BY id DESC
             LIMIT $1
            """,
            int(limit),
        )
    return [dict(r) for r in rows]
