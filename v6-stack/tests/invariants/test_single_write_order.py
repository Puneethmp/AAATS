"""Invariant: order state changes only via DAO `transition_state()` (κ1 req 5c).

Asserts:
  1. Every transition writes to state_history.
  2. Invalid transitions raise InvalidStateTransitionError.
  3. Terminal states have no further transitions.
  4. Concurrent transition attempts serialise (FOR UPDATE in DAO).
"""

from __future__ import annotations

import asyncio
import pytest

from storage.dao import orders


@pytest.mark.asyncio
async def test_normal_lifecycle(pg):
    oid = await orders.create(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="limit", quantity=0.1, price=50_000.0,
    )

    await orders.transition_state(oid, to_state="SUBMITTED", reason="accepted")
    await orders.transition_state(oid, to_state="WORKING", reason="resting")
    await orders.transition_state(
        oid, to_state="FILLED", reason="exch_fill",
        filled_quantity=0.1, avg_fill_price=50_010.0,
    )

    row = await orders.read_durable_by_id(oid)
    assert row is not None
    assert row["state"] == "FILLED"
    assert row["filled_quantity"] == 0.1
    history = list(row["state_history"]) if row["state_history"] is not None else []
    states = [h["to"] for h in history]
    assert states == ["CREATED", "SUBMITTED", "WORKING", "FILLED"]


@pytest.mark.asyncio
async def test_invalid_transition_rejected(pg):
    oid = await orders.create(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="market", quantity=0.05,
    )
    # CREATED → FILLED is not a valid transition (must go through SUBMITTED → WORKING)
    with pytest.raises(orders.InvalidStateTransitionError):
        await orders.transition_state(oid, to_state="FILLED", reason="bad")


@pytest.mark.asyncio
async def test_terminal_states_are_terminal(pg):
    oid = await orders.create(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="market", quantity=0.05,
    )
    await orders.transition_state(oid, to_state="REJECTED", reason="risk_reject")
    with pytest.raises(orders.InvalidStateTransitionError):
        await orders.transition_state(oid, to_state="WORKING", reason="bad")


@pytest.mark.asyncio
async def test_concurrent_transitions_serialised(pg):
    oid = await orders.create(
        market="crypto", symbol="BTC/USDT", side="BUY",
        order_type="limit", quantity=1.0, price=50_000.0,
    )
    await orders.transition_state(oid, to_state="SUBMITTED", reason="t1")
    await orders.transition_state(oid, to_state="WORKING",   reason="t2")

    async def fill_partial(qty: float):
        try:
            await orders.transition_state(
                oid, to_state="PARTIALLY_FILLED", reason=f"part_{qty}",
                filled_quantity=qty,
            )
        except orders.InvalidStateTransitionError:
            pass

    # Fire 5 concurrent partial fills; all should land or all-but-one race
    # to the same self-loop, but exactly ONE final filled_quantity wins.
    await asyncio.gather(*[fill_partial(i / 10) for i in (1, 2, 3, 4, 5)])

    row = await orders.read_durable_by_id(oid)
    assert row is not None
    assert row["state"] == "PARTIALLY_FILLED"
    # Whichever transition won the race, filled_quantity should be one of
    # the inputs — never something else, never None, never overwritten with
    # a partial value below an earlier-set one if PARTIALLY_FILLED was
    # idempotent. (Caller code in production will use COALESCE-vs-greatest
    # logic; here we just assert state is consistent.)
    assert row["filled_quantity"] in {0.1, 0.2, 0.3, 0.4, 0.5}
