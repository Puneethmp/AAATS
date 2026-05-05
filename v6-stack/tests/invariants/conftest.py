"""Pytest fixtures for invariant tests.

Tests run against a *test* Postgres pointed to by the AAATS_PG_TEST_DSN
env var. If the env var isn't set, all invariant tests are skipped (they
are NOT counted as passes — pytest reports them as skipped). This keeps
κ1 deliverable runnable without requiring infrastructure to be live.

To run:
    AAATS_PG_TEST_DSN=postgresql://aaats:<pwd>@localhost:5432/aaats_test \\
    pytest v6-stack/tests/invariants/ -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Make storage/ importable from this repo layout.
ROOT = Path(__file__).resolve().parents[2]   # → v6-stack/
sys.path.insert(0, str(ROOT))

from storage import postgres as _pg
from storage import redis as _redis


def _need_pg() -> str:
    dsn = os.environ.get("AAATS_PG_TEST_DSN", "")
    if not dsn:
        pytest.skip("AAATS_PG_TEST_DSN not set; skipping invariant tests", allow_module_level=False)
    return dsn


@pytest_asyncio.fixture(scope="function")
async def pg():
    """Yields the asyncpg pool, with all aaats.* tables truncated before/after.

    NOTE: requires the alembic migration 0001 to have been applied to the
    test DB. The fixture does NOT run migrations — that's an explicit
    operator step (κ1 req 2: snapshot-then-migrate).
    """
    dsn = _need_pg()
    await _pg.init_pool(dsn=dsn, min_size=1, max_size=4)
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        await _truncate_aaats_tables(conn)
    yield pool
    async with pool.acquire() as conn:
        await _truncate_aaats_tables(conn)
    await _pg.close_pool()


@pytest_asyncio.fixture(scope="function")
async def redis():
    url = os.environ.get("AAATS_REDIS_TEST_URL")
    if not url:
        pytest.skip("AAATS_REDIS_TEST_URL not set", allow_module_level=False)
    r = await _redis.init_redis(url=url)
    # Wipe only test keys (keys starting with aaats:test:)
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="aaats:test:*", count=100)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break
    yield r
    await _redis.close_redis()


async def _truncate_aaats_tables(conn) -> None:
    # Order matters because of FKs (fills→orders, partial_fills→orders, tif_orders→orders).
    tables_in_order = [
        "aaats.fills",
        "aaats.partial_fills",
        "aaats.tif_orders",
        "aaats.orders",
        "aaats.positions",
        "aaats.paper_trades",
        "aaats.audit_log",
        "aaats.halt_audit",
        "aaats.engine_status",
        "aaats.equity_curve",
        "aaats.pnl_attribution",
        "aaats.slippage",
        "aaats.settlement",
        "aaats.dlq",
        "aaats.checkpoints",
        "aaats.reconciliation_runs",
        "aaats.tx_audit",
        "aaats.balance_snapshots",
        "aaats.portfolio_snapshots",
        "aaats.risk_state_snapshots",
        "aaats.alerts_history",
        "aaats.crypto_bars",
        "aaats.funding_rates",
        "compliance.audit_log",
    ]
    for t in tables_in_order:
        try:
            await conn.execute(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE")
        except Exception:  # noqa: BLE001
            # Schema may not have been applied or table missing; tests will fail
            # downstream if so, with a clearer message.
            pass
    # Reset risk_peaks + mode_state seeds.
    await conn.execute("TRUNCATE TABLE aaats.risk_peaks RESTART IDENTITY")
    await conn.execute(
        "INSERT INTO aaats.risk_peaks (scope) VALUES ('portfolio') ON CONFLICT DO NOTHING"
    )
    await conn.execute(
        "INSERT INTO aaats.mode_state (id, mode) VALUES (1, 'paper') ON CONFLICT (id) DO NOTHING"
    )
