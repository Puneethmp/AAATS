"""DAO for aaats.reconciliation_runs.

Per κ1 req 10: this DAO records reconciliation outcomes but performs NO
automatic remediation. Drift detection writes a row; the engine then HALTS
the affected market via the kill_switch (per RR R-12 + AAATS v5.4
behaviour). The operator decides what to do next.

Per κ1 req 5b: `must_reconcile_before_close()` is the structural hook that
the future close-position path will consult — it asserts that a
reconciliation has run since the last halt-clear for the market.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .. import audit, postgres as _pg


async def record_run(
    *,
    market: str,
    db_count: int,
    broker_count: int,
    drift_symbols: list[str],
    warnings: list[str],
    metadata: Optional[dict] = None,
) -> int:
    async with _pg.transaction(label="reconciliation.record") as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO aaats.reconciliation_runs
                (market, db_count, broker_count, drift_count, drift_symbols,
                 warnings, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            market, int(db_count), int(broker_count), len(drift_symbols),
            list(drift_symbols), list(warnings),
            metadata or {},
        )
        audit.track_affected_rows(conn, 1)
        return int(row["id"])


async def latest_run(market: str) -> Optional[dict[str, Any]]:
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM aaats.reconciliation_runs
             WHERE market = $1
             ORDER BY id DESC
             LIMIT 1
            """,
            market,
        )
    return None if row is None else dict(row)


async def must_reconcile_before_close(market: str) -> bool:
    """Returns True if a fresh reconciliation run has been recorded since the
    market's most recent halt-clear (or always-True if there has never been
    a halt). Used as a precondition by the close-position path in κ.

    Returns False if either:
      - no reconciliation run exists for the market and the market has been
        halted at any point (drift unverified).
      - the most recent reconciliation predates the most recent halt-reset.
    """
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        last_recon_row = await conn.fetchrow(
            "SELECT timestamp FROM aaats.reconciliation_runs WHERE market=$1 ORDER BY id DESC LIMIT 1",
            market,
        )
        last_halt_row = await conn.fetchrow(
            """
            SELECT timestamp FROM aaats.halt_audit
             WHERE (market = $1 OR market = 'all')
             ORDER BY id DESC
             LIMIT 1
            """,
            market,
        )
    if last_halt_row is None:
        return True  # never halted → reconciliation precondition trivially holds
    if last_recon_row is None:
        return False  # halt history exists but no recon ever → must reconcile
    return last_recon_row["timestamp"] >= last_halt_row["timestamp"]
