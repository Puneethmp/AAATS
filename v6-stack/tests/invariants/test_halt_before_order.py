"""Invariant: halt-before-order (κ1 req 5a).

The structural enforcement in v6 is:
  - The order-create call site MUST consult `halt.read_durable_current_state()`
    BEFORE inserting a new row in `aaats.orders`.
  - If halted, the call must return without insertion (no row exists).

This test exercises a TINY shim function `_create_order_with_halt_check`
that demonstrates the contract callers must follow. The shim is only
defined within this test module — no production module is modified in κ1.
The test serves as a *structural reminder*: any future code path that
inserts into aaats.orders must wrap this same check.
"""

from __future__ import annotations

import pytest

from storage.dao import halt as halt_dao
from storage.dao import orders


async def _create_order_with_halt_check(market: str, **kwargs) -> int | None:
    """Local shim for the test only — illustrates the required contract."""
    state = await halt_dao.read_durable_current_state(market)
    if state["halted"]:
        return None
    return await orders.create(market=market, **kwargs)


@pytest.mark.asyncio
async def test_no_halt_lets_order_through(pg):
    oid = await _create_order_with_halt_check(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="market", quantity=0.05,
    )
    assert oid is not None and oid > 0


@pytest.mark.asyncio
async def test_halted_market_blocks_order(pg):
    await halt_dao.append_halt_event(
        market="crypto",
        action="halt",
        triggered_by="test",
        reason="invariant test",
    )
    result = await _create_order_with_halt_check(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="market", quantity=0.05,
    )
    assert result is None, "halted market must not insert an order row"

    pool = pg
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT count(*) AS n FROM aaats.orders")
    assert int(row["n"]) == 0


@pytest.mark.asyncio
async def test_global_halt_blocks_all_markets(pg):
    await halt_dao.append_halt_event(
        market="all",
        action="halt",
        triggered_by="test",
        reason="global halt",
    )
    crypto = await _create_order_with_halt_check(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="market", quantity=0.05,
    )
    india = await _create_order_with_halt_check(
        market="india", symbol="RELIANCE", side="BUY",
        order_type="market", quantity=1,
    )
    assert crypto is None
    assert india is None


@pytest.mark.asyncio
async def test_reset_after_halt_reopens(pg):
    await halt_dao.append_halt_event(
        market="crypto", action="halt", triggered_by="t", reason="r",
    )
    await halt_dao.append_halt_event(
        market="crypto", action="reset", triggered_by="op",
        reason="cleared", authorized_by="operator",
    )
    oid = await _create_order_with_halt_check(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="market", quantity=0.05,
    )
    assert oid is not None
