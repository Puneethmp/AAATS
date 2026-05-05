"""Postgres connection pool + transaction primitive.

Async-only (asyncpg). Sync access is intentionally not provided here; if a
caller needs sync (e.g. Alembic migrations, one-off scripts), it goes
through psycopg2 in its own module.

Public surface:
    init_pool(dsn=None, min=2, max=10) → asyncpg.Pool
    close_pool()                       → None
    get_pool()                         → asyncpg.Pool   (raises if not init)
    transaction(label="…")             → async context manager yielding Connection

`transaction()` is the only sanctioned write path. It:
  - acquires a Connection from the pool,
  - opens a database transaction,
  - records a row in aaats.tx_audit on a SEPARATE autocommit connection AFTER
    the transaction completes (success or failure) — so the audit row is
    always written regardless of rollback.
  - retries on serializable / deadlock errors up to MAX_DEADLOCK_RETRIES,
    each retry recorded as a `deadlock_retry` audit row (κ1 req 6).

Risk-critical reads (per κ1 req 11) MUST go through the durable Postgres path
defined here. The Redis cache is for non-risk-critical fast reads only.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import AsyncIterator, Optional

import asyncpg

from .clock import monotonic_ns, utc_now

# Per-transaction counter, async-safe via contextvars. Tracks affected rows so
# `_audit_tx()` can persist them. We can't setattr on a PoolConnectionProxy
# (asyncpg blocks it), so the counter rides on the asyncio task context.
_affected_rows_ctx: ContextVar[list[int]] = ContextVar("_aaats_affected_rows")

LOG = logging.getLogger("storage.postgres")

DEFAULT_MIN_POOL = 2
DEFAULT_MAX_POOL = 10
DEFAULT_COMMAND_TIMEOUT_S = 10.0
MAX_DEADLOCK_RETRIES = 3                # serialization_failure / deadlock_detected

_pool: Optional[asyncpg.Pool] = None


async def init_pool(
    dsn: Optional[str] = None,
    min_size: int = DEFAULT_MIN_POOL,
    max_size: int = DEFAULT_MAX_POOL,
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT_S,
) -> asyncpg.Pool:
    """Initialise the global pool (idempotent)."""
    global _pool
    if _pool is not None:
        return _pool
    dsn = dsn or os.environ.get("AAATS_PG_DSN") or ""
    if not dsn:
        raise RuntimeError("AAATS_PG_DSN env var is required (or pass dsn explicitly)")
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=command_timeout,
        server_settings={"timezone": "UTC", "application_name": "aaats-v6"},
        init=_register_json_codecs,
    )
    LOG.info("postgres pool ready: min=%d max=%d", min_size, max_size)
    return _pool


async def _register_json_codecs(conn: asyncpg.Connection) -> None:
    """Make asyncpg deserialise JSONB/JSON to Python dict/list automatically.

    Without this, JSONB columns come back as raw strings; callers would have
    to `json.loads()` everywhere. With the codec, DAOs pass and receive native
    Python objects.
    """
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads,
        schema="pg_catalog", format="text",
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads,
        schema="pg_catalog", format="text",
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        LOG.info("postgres pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("postgres pool not initialised — call init_pool() first")
    return _pool


@asynccontextmanager
async def transaction(label: str) -> AsyncIterator[asyncpg.Connection]:
    """Sanctioned write path. Yields an asyncpg Connection inside a transaction.

    Records exactly one row in aaats.tx_audit per attempt. Retries on
    serializable / deadlock errors up to MAX_DEADLOCK_RETRIES, each retry
    logged separately.

    Example:
        async with pg.transaction("orders.update_state") as conn:
            await conn.execute(...)
    """
    pool = await init_pool()
    pid = os.getpid()
    attempt = 0
    while True:
        attempt += 1
        started = utc_now()
        started_ns = monotonic_ns()
        status = "in_progress"
        error_msg: Optional[str] = None
        # Mutable single-element list lets callers (audit.track_affected_rows)
        # mutate the counter from within the same async context.
        token = _affected_rows_ctx.set([0])
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    yield conn
                    status = "commit"
            return
        except asyncpg.exceptions.SerializationError:
            status = "deadlock_retry"
            error_msg = "serialization_failure"
            await _audit_tx(pid, label, started, started_ns, status,
                            _affected_rows_ctx.get()[0], error_msg, attempt)
            if attempt >= MAX_DEADLOCK_RETRIES:
                raise
            _affected_rows_ctx.reset(token)
            continue
        except asyncpg.exceptions.DeadlockDetectedError:
            status = "deadlock_retry"
            error_msg = "deadlock_detected"
            await _audit_tx(pid, label, started, started_ns, status,
                            _affected_rows_ctx.get()[0], error_msg, attempt)
            if attempt >= MAX_DEADLOCK_RETRIES:
                raise
            _affected_rows_ctx.reset(token)
            continue
        except Exception as e:  # noqa: BLE001
            status = "rollback"
            error_msg = repr(e)[:1000]
            raise
        finally:
            if status not in ("deadlock_retry",):
                # Final-state audit (commit OR rollback exit). Deadlock retries
                # are audited inside their except branches above.
                await _audit_tx(pid, label, started, started_ns, status,
                                _affected_rows_ctx.get()[0], error_msg, attempt)
                _affected_rows_ctx.reset(token)


async def _audit_tx(
    pid: int,
    label: str,
    started: object,
    started_ns: int,
    status: str,
    affected_rows: int,
    error_msg: Optional[str],
    attempt: int,
) -> None:
    """Write one tx_audit row on a fresh autocommit connection.

    Best-effort: failure to audit MUST NOT break the caller. We log and swallow.
    """
    try:
        pool = get_pool()
        ended = utc_now()
        duration_ms = max(0, (monotonic_ns() - started_ns) // 1_000_000)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO aaats.tx_audit
                  (started_at, ended_at, duration_ms, label, status,
                   affected_rows, error_msg, pid, monotonic_ns)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                started, ended, int(duration_ms),
                f"{label}#{attempt}" if attempt > 1 else label,
                status, affected_rows, error_msg, pid, started_ns,
            )
    except Exception as e:  # noqa: BLE001
        LOG.warning("tx_audit write failed (non-fatal): %s", e)
