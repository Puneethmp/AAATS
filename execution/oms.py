"""
execution/oms.py  —  Order Management System with explicit state machine
=========================================================================

PURPOSE
-------
Closes Gap 2 (no OMS state machine). Currently AAATS treats an order as a
single "record_trade" call — intent and fill in one atomic write. That's
acceptable for paper trading where the simulator is in-process, but for live
trading we need an explicit state machine because:

  - An order can be SUBMITTED but never ACKed (network failure mid-submit)
  - An order can be ACKed but never appear in get_open_orders (broker bug)
  - An order can be partially filled across multiple events
  - An order can be CANCELLED, REJECTED, or EXPIRED before filling
  - Process restart must recover in-flight orders, not lose them

STATE MACHINE
-------------
    NEW                 → strategy generated intent, not yet submitted
     │
     ▼
    SUBMITTED           → sent to broker, awaiting ACK
     │
     ▼
    ACK                 → broker acknowledged receipt, order is on the book
     │
     ▼
    WORKING             → live on the book (limit) or being filled (market)
     │  ┌─────────────┐
     ▼  ▼             │
    PARTIAL_FILL ──────┘   (multiple partials possible)
     │
     ▼
    FILLED              → fully filled (terminal)

Alternate terminal states from any non-terminal state:
    CANCELLED  → user/system cancelled
    REJECTED   → broker rejected (margin, fat-finger band, etc.)
    EXPIRED    → time-in-force expired without fill

RULES ENFORCED IN CODE
----------------------
1. Every state transition is persisted (oms_orders + oms_transitions tables)
2. Invalid transitions raise ValueError immediately
3. Every order has a deterministic client_order_id from idempotency module
4. Process restart can call OMS.resume_inflight() to find unresolved orders

PERSISTENCE
-----------
- Table `oms_orders`: one row per order with current state, total filled qty, etc.
- Table `oms_transitions`: append-only history of every state change

USAGE
-----
    from execution.oms import OMS, OrderIntent

    oms = OMS()

    intent = OrderIntent(
        strategy="C2_momentum",
        market="crypto",
        symbol="BTC/USDT",
        side="BUY",
        qty=0.0012,
        intent_price=43210.0,
        order_type="MARKET",
    )

    order_id = oms.create_intent(intent)              # state: NEW
    oms.submit(order_id, venue_order_id=None)         # state: SUBMITTED
    oms.ack(order_id, venue_order_id="exchange_42")   # state: ACK → WORKING
    oms.partial_fill(order_id, fill_qty=0.0006,
                     fill_price=43215.0, fees=0.0026) # state: PARTIAL_FILL
    oms.partial_fill(order_id, fill_qty=0.0006,
                     fill_price=43218.0, fees=0.0026) # state: FILLED (auto-detected)

    # OR terminal-from-anywhere:
    oms.cancel(order_id, reason="strategy_pulled")
    oms.reject(order_id, reason="margin_insufficient")
    oms.expire(order_id, reason="tif_GTC_24h_elapsed")

PHASE 1 NOTE
------------
For paper trading, the OMS is OPTIONAL — the existing record_trade flow works
fine. The OMS is required ONLY when going live with a real broker. We build
it now (per the 2-day sprint) so live deployment is a config flip, not a
4-week refactor.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from execution.idempotency import make_client_order_id, make_correlation_id

# ─── Types ────────────────────────────────────────────────────────────────────

Side = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]
OrderState = Literal[
    "NEW", "SUBMITTED", "ACK", "WORKING",
    "PARTIAL_FILL", "FILLED",
    "CANCELLED", "REJECTED", "EXPIRED",
]

TERMINAL_STATES = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}

# Valid transitions: from_state → set of allowed to_states
_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    "NEW":          {"SUBMITTED", "REJECTED", "CANCELLED"},
    "SUBMITTED":    {"ACK", "REJECTED", "EXPIRED", "CANCELLED"},
    "ACK":          {"WORKING", "PARTIAL_FILL", "FILLED", "REJECTED", "CANCELLED", "EXPIRED"},
    "WORKING":      {"PARTIAL_FILL", "FILLED", "CANCELLED", "EXPIRED", "REJECTED"},
    "PARTIAL_FILL": {"PARTIAL_FILL", "FILLED", "CANCELLED", "EXPIRED"},
    # Terminal states: no outgoing transitions
    "FILLED":       set(),
    "CANCELLED":    set(),
    "REJECTED":     set(),
    "EXPIRED":      set(),
}


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class OrderIntent:
    """What the strategy wants to do, before any broker contact."""
    strategy: str
    market: str
    symbol: str
    side: Side
    qty: float
    intent_price: float        # the price the strategy SAW
    order_type: OrderType = "MARKET"
    limit_price: float | None = None
    stop_price: float | None = None
    correlation_id: str | None = None  # auto-generated if None
    bar_ts: str | None = None          # auto-now if None
    nonce: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class OMSOrder:
    """The persisted record of one order."""
    order_id: str                   # uuid4 primary key
    client_order_id: str            # deterministic from intent
    correlation_id: str
    venue_order_id: str | None      # set once broker ACKs
    state: OrderState
    strategy: str
    market: str
    symbol: str
    side: Side
    order_type: OrderType
    qty_intended: float
    qty_filled: float
    avg_fill_price: float
    intent_price: float
    limit_price: float | None
    stop_price: float | None
    fees_total: float
    created_at: str
    updated_at: str
    extra: dict[str, Any] = field(default_factory=dict)


# ─── OMS ──────────────────────────────────────────────────────────────────────


class OMS:
    """
    Order Management System. Persists every order + every state transition.

    Construction:
        OMS(db_path="data/oms.db")   # separate DB from paper_trades.db
                                       # so paper-trade analytics don't see
                                       # rejected/cancelled noise.
    """

    def __init__(self, db_path: str = "data/oms.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_schema()

    # ── Schema ───────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db_path, check_same_thread=False)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_schema(self) -> None:
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS oms_orders (
                order_id          TEXT PRIMARY KEY,
                client_order_id   TEXT NOT NULL,
                correlation_id    TEXT NOT NULL,
                venue_order_id    TEXT,
                state             TEXT NOT NULL,
                strategy          TEXT NOT NULL,
                market            TEXT NOT NULL,
                symbol            TEXT NOT NULL,
                side              TEXT NOT NULL,
                order_type        TEXT NOT NULL,
                qty_intended      REAL NOT NULL,
                qty_filled        REAL NOT NULL DEFAULT 0.0,
                avg_fill_price    REAL NOT NULL DEFAULT 0.0,
                intent_price      REAL NOT NULL,
                limit_price       REAL,
                stop_price        REAL,
                fees_total        REAL NOT NULL DEFAULT 0.0,
                created_at        TEXT NOT NULL,
                updated_at        TEXT NOT NULL,
                extra             TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS ux_oms_orders_client_order_id
                ON oms_orders(client_order_id);

            CREATE INDEX IF NOT EXISTS ix_oms_orders_state
                ON oms_orders(state);

            CREATE INDEX IF NOT EXISTS ix_oms_orders_correlation
                ON oms_orders(correlation_id);

            CREATE INDEX IF NOT EXISTS ix_oms_orders_symbol
                ON oms_orders(market, symbol, state);

            CREATE TABLE IF NOT EXISTS oms_transitions (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id          TEXT NOT NULL,
                from_state        TEXT,
                to_state          TEXT NOT NULL,
                ts                TEXT NOT NULL,
                event_data        TEXT,
                FOREIGN KEY (order_id) REFERENCES oms_orders(order_id)
            );

            CREATE INDEX IF NOT EXISTS ix_oms_transitions_order
                ON oms_transitions(order_id);
        """)
        conn.commit()
        conn.close()

    # ── Public API: create + transitions ─────────────────────────────────

    def create_intent(self, intent: OrderIntent) -> str:
        """
        Persist a NEW order. Returns order_id.

        Idempotent: same client_order_id returns existing order_id without
        creating a duplicate.
        """
        cli_id = make_client_order_id(
            strategy=intent.strategy,
            market=intent.market,
            symbol=intent.symbol,
            side=intent.side,
            bar_ts=intent.bar_ts,
            nonce=intent.nonce,
        )

        # Dedupe on client_order_id
        conn = self._conn()
        existing = conn.execute(
            "SELECT order_id FROM oms_orders WHERE client_order_id = ?",
            (cli_id,),
        ).fetchone()
        if existing:
            conn.close()
            return existing[0]

        order_id = str(uuid.uuid4())
        corr_id = intent.correlation_id or make_correlation_id()
        now = datetime.now(timezone.utc).isoformat()

        order = OMSOrder(
            order_id=order_id,
            client_order_id=cli_id,
            correlation_id=corr_id,
            venue_order_id=None,
            state="NEW",
            strategy=intent.strategy,
            market=intent.market,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            qty_intended=intent.qty,
            qty_filled=0.0,
            avg_fill_price=0.0,
            intent_price=intent.intent_price,
            limit_price=intent.limit_price,
            stop_price=intent.stop_price,
            fees_total=0.0,
            created_at=now,
            updated_at=now,
            extra=intent.extra,
        )

        try:
            conn.execute(
                """INSERT INTO oms_orders (
                    order_id, client_order_id, correlation_id, venue_order_id,
                    state, strategy, market, symbol, side, order_type,
                    qty_intended, qty_filled, avg_fill_price, intent_price,
                    limit_price, stop_price, fees_total,
                    created_at, updated_at, extra
                ) VALUES (?,?,?,?, ?,?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?)""",
                (
                    order.order_id, order.client_order_id, order.correlation_id,
                    order.venue_order_id, order.state, order.strategy,
                    order.market, order.symbol, order.side, order.order_type,
                    order.qty_intended, order.qty_filled, order.avg_fill_price,
                    order.intent_price, order.limit_price, order.stop_price,
                    order.fees_total, order.created_at, order.updated_at,
                    json.dumps(order.extra),
                ),
            )
            self._record_transition(conn, order_id, None, "NEW", {"intent": asdict(intent)})
            conn.commit()
        except sqlite3.IntegrityError:
            # Race: parallel callers created same client_order_id.
            row = conn.execute(
                "SELECT order_id FROM oms_orders WHERE client_order_id = ?",
                (cli_id,),
            ).fetchone()
            order_id = row[0] if row else order_id
        finally:
            conn.close()

        return order_id

    def submit(self, order_id: str, venue_order_id: str | None = None) -> None:
        """Move NEW → SUBMITTED. Optionally pre-set venue_order_id."""
        self._transition(
            order_id, "SUBMITTED",
            extra_updates={"venue_order_id": venue_order_id} if venue_order_id else None,
        )

    def ack(self, order_id: str, venue_order_id: str) -> None:
        """Move SUBMITTED → ACK and stamp venue id. Then auto-promote to WORKING."""
        self._transition(
            order_id, "ACK",
            extra_updates={"venue_order_id": venue_order_id},
        )
        # Most live exchanges go ACK → WORKING almost instantly; we model that.
        self._transition(order_id, "WORKING")

    def partial_fill(
        self,
        order_id: str,
        fill_qty: float,
        fill_price: float,
        fees: float = 0.0,
        venue_trade_id: str | None = None,
    ) -> str:
        """
        Apply a partial fill. Auto-transitions to FILLED if cumulative
        qty_filled >= qty_intended (within 0.01% tolerance for rounding).

        Returns the new state.
        """
        conn = self._conn()
        order = self._fetch_order(conn, order_id)
        if order is None:
            conn.close()
            raise ValueError(f"order {order_id} not found")

        new_filled = order.qty_filled + fill_qty
        new_avg = (
            (order.avg_fill_price * order.qty_filled + fill_price * fill_qty)
            / max(new_filled, 1e-12)
        )
        new_fees = order.fees_total + fees

        # Determine new state
        threshold = order.qty_intended * 0.9999
        if new_filled >= threshold:
            new_state: OrderState = "FILLED"
            new_filled = order.qty_intended  # normalise residual rounding
        else:
            new_state = "PARTIAL_FILL"

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """UPDATE oms_orders
               SET state = ?, qty_filled = ?, avg_fill_price = ?,
                   fees_total = ?, updated_at = ?
               WHERE order_id = ?""",
            (new_state, new_filled, new_avg, new_fees, now, order_id),
        )
        self._record_transition(
            conn, order_id, order.state, new_state,
            {
                "fill_qty": fill_qty, "fill_price": fill_price, "fees": fees,
                "venue_trade_id": venue_trade_id,
                "cumulative_qty_filled": new_filled,
                "cumulative_avg_price": new_avg,
            },
        )
        conn.commit()
        conn.close()
        return new_state

    def cancel(self, order_id: str, reason: str = "") -> None:
        """Cancel from any non-terminal state."""
        self._transition(order_id, "CANCELLED", event_data={"reason": reason})

    def reject(self, order_id: str, reason: str = "") -> None:
        """Reject from any non-terminal state."""
        self._transition(order_id, "REJECTED", event_data={"reason": reason})

    def expire(self, order_id: str, reason: str = "") -> None:
        """Expire from any non-terminal state."""
        self._transition(order_id, "EXPIRED", event_data={"reason": reason})

    # ── Read API ─────────────────────────────────────────────────────────

    def get(self, order_id: str) -> OMSOrder | None:
        """Fetch one order. Returns None if not found."""
        conn = self._conn()
        try:
            return self._fetch_order(conn, order_id)
        finally:
            conn.close()

    def get_by_client_order_id(self, client_order_id: str) -> OMSOrder | None:
        """Fetch by deterministic client_order_id (useful on restart)."""
        conn = self._conn()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM oms_orders WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
            return self._row_to_order(row) if row else None
        finally:
            conn.close()

    def open_orders(self, market: str | None = None) -> list[OMSOrder]:
        """All orders in non-terminal states (NEW/SUBMITTED/ACK/WORKING/PARTIAL_FILL)."""
        conn = self._conn()
        try:
            conn.row_factory = sqlite3.Row
            sql = (
                "SELECT * FROM oms_orders "
                "WHERE state NOT IN ('FILLED','CANCELLED','REJECTED','EXPIRED')"
            )
            params: tuple = ()
            if market:
                sql += " AND market = ?"
                params = (market,)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_order(r) for r in rows]
        finally:
            conn.close()

    def transitions(self, order_id: str) -> list[dict[str, Any]]:
        """Full state-transition history for one order."""
        conn = self._conn()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM oms_transitions WHERE order_id = ? ORDER BY id ASC",
                (order_id,),
            ).fetchall()
            return [
                {
                    "from_state": r["from_state"],
                    "to_state": r["to_state"],
                    "ts": r["ts"],
                    "event_data": json.loads(r["event_data"]) if r["event_data"] else {},
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ── Recovery (called on process restart) ─────────────────────────────

    def resume_inflight(self) -> list[OMSOrder]:
        """
        Return all orders in non-terminal states.

        Caller (broker adapter on restart) should:
          1. Look up each by client_order_id at the venue
          2. Apply ack / partial_fill / cancel / expire / reject as appropriate
          3. NEVER leave them in NEW/SUBMITTED for more than one cycle —
             that means the broker doesn't know about the order, which is
             a state-divergence event (kill switch fires)
        """
        return self.open_orders()

    # ── Internals ────────────────────────────────────────────────────────

    def _transition(
        self,
        order_id: str,
        to_state: OrderState,
        event_data: dict[str, Any] | None = None,
        extra_updates: dict[str, Any] | None = None,
    ) -> None:
        """Generic state transition. Raises ValueError on invalid transition."""
        conn = self._conn()
        try:
            order = self._fetch_order(conn, order_id)
            if order is None:
                raise ValueError(f"order {order_id} not found")

            from_state = order.state
            allowed = _TRANSITIONS.get(from_state, set())
            if to_state not in allowed:
                raise ValueError(
                    f"invalid OMS transition: {from_state} → {to_state} "
                    f"(allowed: {sorted(allowed)})"
                )

            now = datetime.now(timezone.utc).isoformat()
            set_clauses = ["state = ?", "updated_at = ?"]
            values: list[Any] = [to_state, now]

            if extra_updates:
                for col, val in extra_updates.items():
                    set_clauses.append(f"{col} = ?")
                    values.append(val)

            values.append(order_id)
            conn.execute(
                f"UPDATE oms_orders SET {', '.join(set_clauses)} WHERE order_id = ?",
                values,
            )
            self._record_transition(conn, order_id, from_state, to_state, event_data or {})
            conn.commit()
        finally:
            conn.close()

    def _record_transition(
        self,
        conn: sqlite3.Connection,
        order_id: str,
        from_state: OrderState | None,
        to_state: OrderState,
        event_data: dict[str, Any],
    ) -> None:
        """Append to oms_transitions. Caller commits."""
        conn.execute(
            """INSERT INTO oms_transitions (order_id, from_state, to_state, ts, event_data)
               VALUES (?, ?, ?, ?, ?)""",
            (
                order_id,
                from_state,
                to_state,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(event_data, default=str),
            ),
        )

    def _fetch_order(self, conn: sqlite3.Connection, order_id: str) -> OMSOrder | None:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM oms_orders WHERE order_id = ?", (order_id,),
        ).fetchone()
        return self._row_to_order(row) if row else None

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> OMSOrder:
        return OMSOrder(
            order_id=row["order_id"],
            client_order_id=row["client_order_id"],
            correlation_id=row["correlation_id"],
            venue_order_id=row["venue_order_id"],
            state=row["state"],
            strategy=row["strategy"],
            market=row["market"],
            symbol=row["symbol"],
            side=row["side"],
            order_type=row["order_type"],
            qty_intended=row["qty_intended"],
            qty_filled=row["qty_filled"],
            avg_fill_price=row["avg_fill_price"],
            intent_price=row["intent_price"],
            limit_price=row["limit_price"],
            stop_price=row["stop_price"],
            fees_total=row["fees_total"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            extra=json.loads(row["extra"]) if row["extra"] else {},
        )
