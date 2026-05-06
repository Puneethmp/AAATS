"""DAO for aaats.audit_log — SHA-256 hash chain.

The hash chain is computed by a BEFORE INSERT trigger in Postgres
(migration 0001 §3). The DAO only:
  - inserts new rows
  - verifies chain integrity end-to-end
  - exports / seeds the chain for v5 → v6 migration

NEVER UPDATE/DELETE on this table at the DAO layer; the chain assumes
append-only.
"""

from __future__ import annotations

import hashlib
from datetime import timezone
from typing import Any, Optional

import asyncpg

from .. import audit, postgres as _pg


async def append(
    *,
    module: str,
    event_type: str,
    market: Optional[str] = None,
    details: Optional[dict] = None,
    result: Optional[str] = None,
    reason: Optional[str] = None,
) -> int:
    """Append a row. Returns the new row id. Trigger fills prev_hash + entry_hash."""
    async with _pg.transaction(label="audit_log.append") as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO aaats.audit_log
                (market, module, event_type, details, result, reason, entry_hash)
            VALUES ($1, $2, $3, $4, $5, $6, '\\x00'::bytea)
            RETURNING id
            """,
            market, module, event_type,
            details or {},
            result, reason,
        )
        audit.track_affected_rows(conn, 1)
        return int(row["id"])


async def latest_hash() -> Optional[bytes]:
    """Return the most recent entry_hash, or None if the chain is empty."""
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT entry_hash FROM aaats.audit_log ORDER BY id DESC LIMIT 1"
        )
    return None if row is None else bytes(row["entry_hash"])


async def verify_chain(*, limit: Optional[int] = None) -> tuple[bool, Optional[int], str]:
    """Walk the chain forward; return (ok, broken_at_id, message).

    For each row we recompute the SHA-256 of the canonical payload and
    compare against the stored entry_hash. Also verifies prev_hash matches
    the previous row's entry_hash. If `limit` is set, only the last `limit`
    rows are checked (cheaper for hot-path probes).
    """
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        if limit is None:
            rows = await conn.fetch(
                """
                SELECT id, timestamp, market, module, event_type, details::text AS details,
                       result, reason, prev_hash, entry_hash
                  FROM aaats.audit_log
                 ORDER BY id ASC
                """
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, timestamp, market, module, event_type, details::text AS details,
                       result, reason, prev_hash, entry_hash
                  FROM aaats.audit_log
                 ORDER BY id DESC
                 LIMIT $1
                """,
                int(limit),
            )
            rows = list(reversed(rows))

    prev_expected: Optional[bytes] = None
    for r in rows:
        # Verify chain link
        prev_actual = bytes(r["prev_hash"]) if r["prev_hash"] is not None else None
        if prev_expected is not None and prev_actual != prev_expected:
            return (False, int(r["id"]),
                    f"prev_hash mismatch at id={r['id']}")
        # Recompute entry_hash exactly the way the trigger does (see migration 0001).
        # Deterministic UTC microsecond ISO8601 — matches `to_char(..., 'YYYY-MM-DD"T"HH24:MI:SS.US')`.
        prev_hex = prev_actual.hex() if prev_actual is not None else "<genesis>"
        ts_str = r["timestamp"].astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')
        payload = (
            f"{prev_hex}|{r['id']}|{ts_str}|"
            f"{r['market'] or ''}|{r['module']}|{r['event_type']}|"
            f"{r['details']}|{r['result'] or ''}|{r['reason'] or ''}"
        )
        recomputed = hashlib.sha256(payload.encode("utf-8")).digest()
        if recomputed != bytes(r["entry_hash"]):
            return (False, int(r["id"]),
                    f"entry_hash mismatch at id={r['id']}")
        prev_expected = bytes(r["entry_hash"])
    return (True, None, f"chain ok ({len(rows)} rows)")


async def seed_genesis_from_v5_final_hash(v5_hex_hash: str) -> int:
    """Seed the v6 chain by inserting one bookkeeping row whose `prev_hash`
    references the v5 final hash. Idempotent: if the chain is non-empty,
    raises (operator must use a fresh DB or downgrade first).

    Used once during migration (Section 3.4 of MIGRATION_PLAN_V5_TO_V6.md).
    """
    if await latest_hash() is not None:
        raise RuntimeError("audit chain not empty — refusing to re-seed")
    # We can't pre-load prev_hash via the trigger path (it queries the table),
    # so the genesis row's prev_hash will be NULL by trigger behavior. Instead,
    # we record the v5 final hash inside the `details` JSON so the chain audit
    # can verify continuity at v5→v6 boundary out-of-band. The operator
    # acknowledges this design at Gate κ-A.
    return await append(
        module="migration",
        event_type="v5_to_v6_audit_chain_seed",
        details={"v5_final_audit_hash": v5_hex_hash},
        reason="κ1 chain seed (operator-approved)",
        result="OK",
    )
