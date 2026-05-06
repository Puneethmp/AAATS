"""DAO for aaats.orders — finite-state machine.

Enforces in-application what the schema enforces structurally:

  * Single-write invariant (κ1 req 5c): every state transition goes through
    `transition_state()`. No raw UPDATE elsewhere.
  * No-duplicate (market, client_order_id) (κ1 req 5d): the unique partial
    index in migration 0001 is the structural enforcement; this DAO surfaces
    the constraint as a typed exception.

State machine (mirrors v5 execution lifecycle):

    CREATED → SUBMITTED → WORKING → PARTIALLY_FILLED → FILLED
                        \\          \\
                         \\           → CANCELLED
                          → CANCELLED → EXPIRED → REJECTED

Terminal states: FILLED, CANCELLED, EXPIRED, REJECTED.

`state_history` JSONB column accumulates a list of {from, to, ts, reason}
records — append-only audit of transitions.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg

from .. import audit, postgres as _pg
from ..clock import utc_now_iso


VALID_TRANSITIONS: dict[str, set[str]] = {
    "CREATED":           {"SUBMITTED", "REJECTED", "CANCELLED"},
    "SUBMITTED":         {"WORKING", "REJECTED", "CANCELLED"},
    "WORKING":           {"PARTIALLY_FILLED", "FILLED", "CANCELLED", "EXPIRED"},
    "PARTIALLY_FILLED":  {"PARTIALLY_FILLED", "FILLED", "CANCELLED", "EXPIRED"},
    "FILLED":            set(),
    "CANCELLED":         set(),
    "EXPIRED":           set(),
    "REJECTED":          set(),
}

TERMINAL_STATES: frozenset[str] = frozenset({"FILLED", "CANCELLED", "EXPIRED", "REJECTED"})


class DuplicateClientOrderIdError(Exception):
    """Raised when a (market, client_order_id) collision occurs."""


class InvalidStateTransitionError(Exception):
    """Raised when a state transition is not in VALID_TRANSITIONS."""


async def create(
    *,
    market: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: Optional[float] = None,
    time_in_force: Optional[str] = None,
    client_order_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> int:
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY|SELL, got {side!r}")
    if quantity <= 0:
        raise ValueError(f"quantity must be > 0, got {quantity!r}")
    metadata = metadata or {}
    history0 = [{"from": None, "to": "CREATED", "ts": utc_now_iso(), "reason": "create"}]
    try:
        async with _pg.transaction(label="orders.create") as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO aaats.orders
                  (client_order_id, market, symbol, side, order_type, quantity,
                   price, time_in_force, state, state_history, metadata)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'CREATED',$9,$10)
                RETURNING id
                """,
                client_order_id, market, symbol, side, order_type,
                float(quantity), price, time_in_force, history0, metadata,
            )
            audit.track_affected_rows(conn, 1)
            return int(row["id"])
    except asyncpg.exceptions.UniqueViolationError as e:
        raise DuplicateClientOrderIdError(
            f"(market={market!r}, client_order_id={client_order_id!r}) already exists"
        ) from e


async def transition_state(
    order_id: int,
    *,
    to_state: str,
    reason: str,
    filled_quantity: Optional[float] = None,
    avg_fill_price: Optional[float] = None,
) -> str:
    """Atomically move an order to `to_state`. Returns the new state.

    The single-write invariant is preserved by:
      1. Locking the row inside the transaction (SELECT ... FOR UPDATE).
      2. Validating the transition against VALID_TRANSITIONS.
      3. Performing one UPDATE that flips state + appends to state_history.

    Callers must NOT issue raw UPDATE statements against this table.
    """
    if to_state not in VALID_TRANSITIONS:
        raise InvalidStateTransitionError(f"unknown target state {to_state!r}")
    async with _pg.transaction(label=f"orders.transition[{to_state}]") as conn:
        row = await conn.fetchrow(
            "SELECT id, state, state_history FROM aaats.orders WHERE id=$1 FOR UPDATE",
            order_id,
        )
        if row is None:
            raise InvalidStateTransitionError(f"order id={order_id} not found")
        from_state = row["state"]
        if from_state == to_state and to_state == "PARTIALLY_FILLED":
            # PARTIALLY_FILLED → PARTIALLY_FILLED is the only self-loop
            allowed = True
        else:
            allowed = to_state in VALID_TRANSITIONS.get(from_state, set())
        if not allowed:
            raise InvalidStateTransitionError(
                f"order {order_id}: {from_state} → {to_state} not allowed"
            )
        new_history = list(row["state_history"]) if row["state_history"] is not None else []
        new_history.append({
            "from": from_state, "to": to_state,
            "ts": utc_now_iso(), "reason": reason,
        })
        await conn.execute(
            """
            UPDATE aaats.orders
               SET state              = $1,
                   state_history      = $2,
                   filled_quantity    = COALESCE($3, filled_quantity),
                   avg_fill_price     = COALESCE($4, avg_fill_price),
                   last_state_change  = now(),
                   submitted_at       = CASE WHEN $1 = 'SUBMITTED' AND submitted_at IS NULL
                                             THEN now() ELSE submitted_at END
             WHERE id = $5
            """,
            to_state, new_history,
            filled_quantity, avg_fill_price, order_id,
        )
        audit.track_affected_rows(conn, 1)
        return to_state


async def read_durable_by_id(order_id: int) -> Optional[dict[str, Any]]:
    """Risk-safe read by id (Postgres). Returns dict or None."""
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM aaats.orders WHERE id=$1", order_id,
        )
    return None if row is None else dict(row)


async def read_durable_pending(market: str) -> list[dict[str, Any]]:
    """Risk-safe read of non-terminal orders for a market."""
    pool = _pg.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM aaats.orders
             WHERE market = $1
               AND state NOT IN ('FILLED','CANCELLED','EXPIRED','REJECTED')
             ORDER BY id ASC
            """,
            market,
        )
    return [dict(r) for r in rows]
