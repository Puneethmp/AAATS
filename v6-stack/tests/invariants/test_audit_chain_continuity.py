"""Invariant: aaats.audit_log SHA-256 chain remains continuous (κ1 req 5e).

Asserts:
  1. First row has prev_hash IS NULL.
  2. Subsequent rows' prev_hash equals the previous row's entry_hash.
  3. Re-computing entry_hash from canonical payload matches stored value.
  4. Tampering with one row is detected by verify_chain().
  5. v5 → v6 chain seed records the v5 final hash.
"""

from __future__ import annotations

import pytest

from storage.dao import audit_log


@pytest.mark.asyncio
async def test_chain_starts_with_null_prev(pg):
    rid = await audit_log.append(
        module="test", event_type="test_first", details={"k": 1},
    )
    pool = pg
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT prev_hash, entry_hash FROM aaats.audit_log WHERE id=$1", rid)
    assert row is not None
    assert row["prev_hash"] is None
    assert row["entry_hash"] is not None
    assert len(bytes(row["entry_hash"])) == 32   # SHA-256


@pytest.mark.asyncio
async def test_subsequent_rows_chain(pg):
    a = await audit_log.append(module="test", event_type="A", details={"i": 1})
    b = await audit_log.append(module="test", event_type="B", details={"i": 2})
    c = await audit_log.append(module="test", event_type="C", details={"i": 3})
    assert a < b < c
    pool = pg
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, prev_hash, entry_hash FROM aaats.audit_log ORDER BY id ASC"
        )
    assert len(rows) >= 3
    for prev_row, this_row in zip(rows, rows[1:]):
        assert bytes(this_row["prev_hash"]) == bytes(prev_row["entry_hash"])


@pytest.mark.asyncio
async def test_verify_chain_passes_on_clean(pg):
    for i in range(5):
        await audit_log.append(module="t", event_type="evt", details={"i": i})
    ok, broken_at, msg = await audit_log.verify_chain()
    assert ok, f"chain should be clean; got {msg!r}"
    assert broken_at is None


@pytest.mark.asyncio
async def test_verify_chain_detects_tamper(pg):
    rid = await audit_log.append(module="t", event_type="evt", details={"i": 1})
    await audit_log.append(module="t", event_type="evt", details={"i": 2})
    # Tamper: directly UPDATE the details of the first row (this should
    # never happen in production; we simulate corruption to verify the
    # chain detector). No automatic remediation is applied (κ1 req 10).
    pool = pg
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE aaats.audit_log SET details = $1::jsonb WHERE id = $2",
            '{"i": 999}', rid,
        )
    ok, broken_at, msg = await audit_log.verify_chain()
    assert not ok, "tamper should be detected"
    assert broken_at is not None
    assert "mismatch" in msg


@pytest.mark.asyncio
async def test_v5_seed_records_v5_final_hash(pg):
    fake_v5_hash = "deadbeef" * 8
    rid = await audit_log.seed_genesis_from_v5_final_hash(fake_v5_hash)
    pool = pg
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT details::text FROM aaats.audit_log WHERE id=$1", rid,
        )
    assert row is not None
    assert fake_v5_hash in row["details"]
