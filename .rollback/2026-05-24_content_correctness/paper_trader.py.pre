"""
Paper trade executor — writes simulated trades to data/paper_trades.db.

The Streamlit dashboard reads this DB via data_layer.py. This module is the
sole writer; the web app never writes here.

Schema v2 additions (2026-05-08):
  strategy   -- AAATS strategy ID (e.g. "C1_stat_arb", "C2_momentum", "C5b_funding_arb")
  entry_time -- ISO timestamp of position open (same as timestamp for BUY rows)
  exit_time  -- ISO timestamp of position close (NULL for open positions)
  pnl_pct    -- percentage PnL at close (NULL for open positions)
  notes      -- JSON blob: confidence, exit_reason, r_multiple, size_usd, skipped_regime
  size_usd   -- notional value of trade in USD/INR

A trades VIEW aliases paper_trades for the metrics exporter.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from foundation.logger import get_logger
from execution.idempotency import (
    _ensure_dedupe_index,
    dedupe_check,
    make_client_order_id,
    make_correlation_id,
)

_log = get_logger("execution", "paper_trader")

Action = Literal["BUY", "SELL"]

_CREATE_SQL = (
    "CREATE TABLE IF NOT EXISTS paper_trades ("
    "id          TEXT PRIMARY KEY,"
    "timestamp   TEXT NOT NULL,"
    "market      TEXT NOT NULL,"
    "symbol      TEXT NOT NULL,"
    "action      TEXT NOT NULL,"
    "shares      REAL NOT NULL,"
    "price       REAL NOT NULL,"
    "value       REAL NOT NULL,"
    "signal      TEXT,"
    "regime      TEXT,"
    "risk_action TEXT,"
    "pnl         REAL DEFAULT 0.0,"
    "note        TEXT,"
    "strategy    TEXT DEFAULT '',"
    "entry_time  TEXT,"
    "exit_time   TEXT,"
    "pnl_pct     REAL,"
    "notes       TEXT,"
    "size_usd    REAL DEFAULT 0.0"
    ")"
)

_VIEW_SQL = (
    "CREATE VIEW IF NOT EXISTS trades AS "
    "SELECT id, timestamp, market, symbol, action, shares, price, value, "
    "signal, regime, risk_action, pnl, note, "
    "strategy, entry_time, exit_time, pnl_pct, notes, size_usd "
    "FROM paper_trades"
)

# Migration: safely add v2 columns to any existing v1 DB
_MIGRATE_SQLS = [
    "ALTER TABLE paper_trades ADD COLUMN strategy        TEXT    DEFAULT ''",
    "ALTER TABLE paper_trades ADD COLUMN entry_time      TEXT",
    "ALTER TABLE paper_trades ADD COLUMN exit_time       TEXT",
    "ALTER TABLE paper_trades ADD COLUMN pnl_pct         REAL",
    "ALTER TABLE paper_trades ADD COLUMN notes           TEXT",
    "ALTER TABLE paper_trades ADD COLUMN size_usd        REAL    DEFAULT 0.0",
    # 2026-05-23 healer: scripts/init_db.py's CREATE schema omits
    # `value`; without this migration step a fresh DB created by
    # init_db.py FIRST (then opened by _conn) is missing the column
    # and every record_trade INSERT fails with "no such column: value".
    # Default 0.0 because ALTER TABLE ADD COLUMN cannot enforce NOT NULL
    # against existing rows; the INSERT path always passes a real value.
    "ALTER TABLE paper_trades ADD COLUMN value           REAL    DEFAULT 0.0",
    # value-with-risk_action pair: risk_action is NOT NULL in the CREATE
    # schema but absent from init_db; same healer rationale.
    "ALTER TABLE paper_trades ADD COLUMN risk_action     TEXT    DEFAULT 'ALLOW'",
    # v3 idempotency columns (gap 4) — also created via execution.idempotency
    # but kept here so a fresh DB built by paper_trader._conn() has them too.
    "ALTER TABLE paper_trades ADD COLUMN client_order_id TEXT",
    "ALTER TABLE paper_trades ADD COLUMN correlation_id  TEXT",
]


def _conn(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(_CREATE_SQL)
    for sql in _MIGRATE_SQLS:
        try:
            c.execute(sql)
        except sqlite3.OperationalError as exc:
            _log.debug(f"paper_trades migration noop ({sql[:40]}...): {exc}")
    # v3: UNIQUE INDEX on client_order_id — last-line dedupe guarantee
    try:
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_trades_client_order_id "
            "ON paper_trades(client_order_id) WHERE client_order_id IS NOT NULL"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS ix_paper_trades_correlation_id "
            "ON paper_trades(correlation_id)"
        )
    except sqlite3.OperationalError as exc:
        _log.debug(f"paper_trades index create noop: {exc}")
    try:
        c.execute("DROP VIEW IF EXISTS trades")
        c.execute(_VIEW_SQL)
    except sqlite3.OperationalError as exc:
        _log.debug(f"paper_trades view rebuild noop: {exc}")
    c.commit()
    return c


def _check_sell_buy_share_equality(
    c: sqlite3.Connection,
    strategy: str,
    symbol: str,
    sell_shares: float,
) -> None:
    """
    Post-INSERT SELL/BUY share-equality detector (P1 guardrail, 2026-05-15).

    For each SELL row just inserted, find the FIFO-matching BUY for the same
    (strategy, symbol) — the k-th BUY in timestamp ASC order, where k = total
    SELL count for that pair (including this row). If shares differ by more
    than 1e-9, emit a warning. Detection-only: never halts, never modifies.

    The reconciler / ledger migration owns HALT decisions for share drift.
    """
    try:
        n_sells = c.execute(
            "SELECT COUNT(*) FROM paper_trades "
            "WHERE strategy = ? AND symbol = ? AND action = 'SELL'",
            (strategy, symbol),
        ).fetchone()[0]
        if n_sells <= 0:
            return
        row = c.execute(
            "SELECT shares FROM paper_trades "
            "WHERE strategy = ? AND symbol = ? AND action = 'BUY' "
            "ORDER BY timestamp ASC, id ASC LIMIT 1 OFFSET ?",
            (strategy, symbol, n_sells - 1),
        ).fetchone()
        if row is None:
            return  # orphan SELL — reconciler's problem, not this hook's
        buy_shares = float(row[0])
        delta = abs(sell_shares - buy_shares)
        if delta > 1e-9:
            _log.warning(
                "SELL/BUY share mismatch | strategy={} symbol={} "
                "buy_shares={} sell_shares={} delta={:.10f}",
                strategy, symbol, buy_shares, sell_shares, delta,
            )
            _bump_share_mismatch_counter(strategy, symbol)
    except sqlite3.OperationalError:
        # Schema variant (e.g. test DB without strategy column) — silently skip.
        return


def _bump_share_mismatch_counter(strategy: str, symbol: str) -> None:
    """Persist a per-(strategy,symbol) mismatch tally for the Prometheus exporter.

    Cross-container handoff: paper_trader (aaats-paper-crypto) writes to the
    shared data/ bind mount; metrics_exporter (aaats-metrics) reads on scrape.
    Best-effort — never blocks the trade write path.
    """
    try:
        import json as _json
        counter_path = Path(__file__).resolve().parent.parent / "data" / "share_equality_mismatches.json"
        state: dict[str, int] = {}
        if counter_path.exists():
            try:
                state = _json.loads(counter_path.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        key = f"{strategy}|{symbol}"
        state[key] = int(state.get(key, 0)) + 1
        counter_path.write_text(_json.dumps(state), encoding="utf-8")
    except Exception:
        return


def record_trade(
    db_path: str,
    market: str,
    symbol: str,
    action: Action,
    shares: float,
    price: float,
    signal: str = "",
    regime: str = "",
    risk_action: str = "ALLOW",
    pnl: float = 0.0,
    note: str = "",
    strategy: str = "",
    entry_time: str | None = None,
    exit_time: str | None = None,
    pnl_pct: float | None = None,
    notes: dict[str, Any] | None = None,
    size_usd: float = 0.0,
    client_order_id: str | None = None,
    correlation_id: str | None = None,
    bar_ts: datetime | str | None = None,
    nonce: int = 0,
) -> str:
    """
    Insert one paper trade row. Returns the trade id (UUID4 primary key).

    Idempotency (v3 — gap 4):
      - If `client_order_id` is supplied, dedupe before insert. Duplicate
        intent returns the prior trade id and writes NOTHING new.
      - If `client_order_id` is None, derive deterministically from
        (strategy, market, symbol, action, bar_ts, nonce).
      - If `correlation_id` is None, generate a fresh uuid4 (one per intent).

    The dedupe layer + the UNIQUE INDEX in paper_trades together ensure that
    a network blip causing a retry never doubles a position.
    """
    # ── Idempotency: derive ids if caller didn't pass them ────────────────
    if client_order_id is None:
        client_order_id = make_client_order_id(
            strategy=strategy or f"{market}_directional",
            market=market,
            symbol=symbol,
            side=action,
            bar_ts=bar_ts,
            nonce=nonce,
        )
    if correlation_id is None:
        correlation_id = make_correlation_id()

    # ── Dedupe check (last-line UNIQUE INDEX is the safety net) ──────────
    existed, prior_id = dedupe_check(db_path, client_order_id)
    if existed:
        _log.warning(
            "PAPER duplicate suppressed | cli_id={} | prior_trade={} | "
            "{} {} @ {:.4f} x{:.6f} strat={}",
            client_order_id[:12], prior_id, action, symbol, price, shares,
            strategy or signal,
        )
        return prior_id  # caller treats this as success — same intent already recorded

    # ── Insert (regular path) ─────────────────────────────────────────────
    trade_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    value = round(shares * price, 4)

    if entry_time is None:
        entry_time = ts if action == "BUY" else None
    if size_usd == 0.0:
        size_usd = round(value, 4)

    notes_json = json.dumps(notes) if notes else None

    c = _conn(db_path)
    try:
        c.execute(
            "INSERT INTO paper_trades "
            "(id,timestamp,market,symbol,action,shares,price,value,signal,regime,"
            "risk_action,pnl,note,strategy,entry_time,exit_time,pnl_pct,notes,size_usd,"
            "client_order_id,correlation_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (trade_id, ts, market, symbol, action, shares, price, value,
             signal, regime, risk_action, pnl, note,
             strategy, entry_time, exit_time, pnl_pct, notes_json, size_usd,
             client_order_id, correlation_id),
        )
        c.commit()
    except sqlite3.IntegrityError as exc:
        # UNIQUE INDEX caught a race (parallel callers both passed
        # dedupe_check). Look up the winner — if found, return its id.
        # If NOT found, the IntegrityError was NOT a duplicate-race
        # but some other constraint violation (e.g. the 2026-05-23
        # bug: init_db.py declared `id INTEGER PRIMARY KEY` so writing
        # uuid strings raised "datatype mismatch", which was silently
        # treated as a duplicate and the row was never persisted).
        # Re-raise so the caller can see the failure instead of
        # accumulating orphan strategy state.
        row = c.execute(
            "SELECT id FROM paper_trades WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        c.close()
        if row is None:
            _log.error(
                "PAPER record_trade IntegrityError without a winning row "
                "(client_order_id={}); re-raising — likely schema mismatch "
                "or constraint violation, NOT a duplicate race: {}",
                client_order_id[:12], exc,
            )
            raise
        winner = row[0]
        _log.warning(
            "PAPER duplicate race resolved by UNIQUE INDEX | cli_id={} | winner={}",
            client_order_id[:12], winner,
        )
        return winner
    if action == "SELL":
        _check_sell_buy_share_equality(c, strategy, symbol, shares)
    c.close()
    _log.info(
        "PAPER {} {} @ {:.4f} x{:.6f} | strat={} | regime={} | cli={} | corr={}",
        action, symbol, price, shares, strategy or signal, regime,
        client_order_id[:12], correlation_id[:8],
    )
    return trade_id
