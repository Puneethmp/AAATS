"""Invariant: no two orders may share (market, client_order_id) (κ1 req 5d).

Structurally enforced by a unique partial index in migration 0001:
    CREATE UNIQUE INDEX … ON aaats.orders (market, client_order_id)
        WHERE client_order_id IS NOT NULL;

This test asserts that:
  1. The DAO's `create()` raises DuplicateClientOrderIdError on collision
     within a market.
  2. Same client_order_id across DIFFERENT markets is allowed.
  3. NULL client_order_id is allowed multiple times (the partial index
     intentionally does not constrain NULLs).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from storage.dao import orders


@pytest.mark.asyncio
async def test_duplicate_within_market_rejected(pg):
    cid = "cli-123"
    oid1 = await orders.create(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="limit", quantity=0.1, price=50_000.0,
        client_order_id=cid,
    )
    assert oid1 > 0

    with pytest.raises(orders.DuplicateClientOrderIdError):
        await orders.create(
            market="crypto", symbol="ETH/USDT", side="BUY",
            order_type="limit", quantity=1.0, price=2_000.0,
            client_order_id=cid,
        )


@pytest.mark.asyncio
async def test_same_id_different_markets_ok(pg):
    cid = "cli-cross-market"
    oid_crypto = await orders.create(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="limit", quantity=0.1, price=50_000.0,
        client_order_id=cid,
    )
    oid_india = await orders.create(
        market="india", symbol="RELIANCE", side="BUY",
        order_type="limit", quantity=10, price=2500.0,
        client_order_id=cid,
    )
    assert oid_crypto != oid_india


@pytest.mark.asyncio
async def test_null_client_order_id_allowed_multiple(pg):
    a = await orders.create(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="market", quantity=0.05,
    )
    b = await orders.create(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="market", quantity=0.07,
    )
    assert a != b
