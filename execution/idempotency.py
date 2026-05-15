"""
execution/idempotency.py  —  Deterministic clientOrderId + dedupe layer
=======================================================================

PURPOSE
-------
Every order intent in AAATS must produce a deterministic, reproducible
`client_order_id` derived from (strategy, symbol, intent_type, bar_timestamp,
nonce). Retrying an order after a network blip or process restart MUST
re-derive the same id and be deduped at the persistence layer.

This module solves:
  Gap 4 (idempotent clientOrderId) — every order has a stable identity
  Gap 5 (correlation tracking) — link intent → decision → fill across logs

DESIGN
------
- `make_client_order_id()` returns a 32-char hex sha256 prefix.
  Inputs: strategy, market, symbol, side, bar_ts (UTC ISO), nonce (default 0).
  Same inputs → same id forever.
- `make_correlation_id()` returns uuid4 — one per intent — used to link
  the audit-trail signal entry, decision entry, order placement, fill,
  and any errors in one queryable thread.
- `dedupe_check()` peeks at paper_trades by client_order_id BEFORE inserting.
  Returns (existed, prior_trade_id) to caller. Caller decides retry-vs-skip.
- `nonce_for_retry()` lets a caller deliberately bump the nonce when it WANTS
  a fresh order id (e.g. resubmitting after explicit cancel).

INTEGRATION
-----------
Called by:
  - execution/paper_trader.record_trade() — derives & checks dedup
  - trading/funding_arb.py — entry/exit legs
  - trading/live_paper_runner.execute() — per-symbol BUY/SELL

THE RULES
---------
1. Never use random uuid for trade identity. uuid only as PRIMARY KEY tag.
2. Client_order_id IS the broker-facing identity.
3. Two writes with the same client_order_id MUST return the same trade row.
4. The dedupe table is the source of truth. paper_trades.id is just a row key.

PRODUCTION SAFETY
-----------------
- SQLite UNIQUE INDEX on client_order_id rejects duplicate writes at DB level
  even if the in-memory check races. This is the last-line guarantee.
- Bar_timestamp normalisation: rounds DOWN to nearest minute UTC to avoid
  microsecond drift between machines/cycles producing different ids.
- Module is import-time-safe — no side effects, all I/O lazy.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# ─── Public types ────────────────────────────────────────────────────────────

Side = Literal["BUY", "SELL"]


# ─── Public API ──────────────────────────────────────────────────────────────


def make_client_order_id(
    strategy: str,
    market: str,
    symbol: str,
    side: Side,
    bar_ts: datetime | str | None = None,
    nonce: int = 0,
) -> str:
    """
    Return a deterministic 32-char hex client_order_id.

    Same inputs ALWAYS produce the same id.

    Args:
        strategy:   AAATS strategy id, e.g. "C5b_funding_arb", "C2_momentum".
        market:     "crypto" | "india" | "us".
        symbol:     Trading symbol, e.g. "BTC/USDT".
        side:       "BUY" | "SELL".
        bar_ts:     Bar timestamp this order belongs to. None = now (rounded
                    DOWN to nearest minute UTC).
        nonce:      Disambiguator for legitimate retries with same intent
                    (e.g. resubmit after explicit cancel). Default 0.

    Returns:
        32-char hex sha256 prefix.
    """
    ts = _normalise_bar_ts(bar_ts)
    payload = f"{strategy}|{market}|{symbol}|{side}|{ts}|{nonce}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def make_correlation_id() -> str:
    """Return a fresh uuid4 to thread one intent's log entries together."""
    return str(uuid.uuid4())


def dedupe_check(
    db_path: str,
    client_order_id: str,
) -> tuple[bool, str | None]:
    """
    Look up an existing trade by client_order_id.

    Returns:
        (existed, prior_trade_id)
          existed=False, prior=None    — safe to insert
          existed=True,  prior=<uuid>  — duplicate; caller decides what to do
    """
    conn = _ensure_dedupe_index(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM paper_trades WHERE client_order_id = ? LIMIT 1",
            (client_order_id,),
        ).fetchone()
        if row is None:
            return False, None
        return True, row[0]
    finally:
        conn.close()


def nonce_for_retry(prior_nonce: int = 0) -> int:
    """
    Bump a nonce when you genuinely want a fresh client_order_id
    (e.g. you explicitly cancelled the prior order and want to submit a new
    one with a deliberately different identity). Default behaviour for a
    blind retry should be `nonce=0` so the dedupe layer catches it.
    """
    return prior_nonce + 1


# ─── Internals ───────────────────────────────────────────────────────────────


def _normalise_bar_ts(bar_ts: datetime | str | None) -> str:
    """
    Round DOWN to nearest UTC minute and serialise as ISO-8601.

    Two callers in the same cycle minute produce the same string,
    even if their datetime.now() differs by microseconds.
    """
    if bar_ts is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(bar_ts, str):
        dt = datetime.fromisoformat(bar_ts.replace("Z", "+00:00"))
    else:
        dt = bar_ts

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.replace(second=0, microsecond=0).astimezone(timezone.utc)
    return dt.isoformat()


def _ensure_dedupe_index(db_path: str) -> sqlite3.Connection:
    """
    Ensure paper_trades has client_order_id and correlation_id columns +
    UNIQUE INDEX on client_order_id. Idempotent — safe to call from anywhere.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")

    # Add columns if missing (additive migrations, never destructive)
    for sql in (
        "ALTER TABLE paper_trades ADD COLUMN client_order_id TEXT",
        "ALTER TABLE paper_trades ADD COLUMN correlation_id  TEXT",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists

    # UNIQUE INDEX — last-line DB-level guarantee against double-fires.
    # Partial index excludes NULLs so legacy rows without client_order_id
    # don't collide with each other.
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_trades_client_order_id "
            "ON paper_trades(client_order_id) "
            "WHERE client_order_id IS NOT NULL"
        )
    except sqlite3.OperationalError:
        pass

    # Plain index on correlation_id — fast joins for audit trail forensics
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_paper_trades_correlation_id "
            "ON paper_trades(correlation_id)"
        )
    except sqlite3.OperationalError:
        pass

    conn.commit()
    return conn


# ─── Convenience for trade writers (paper_trader.record_trade) ───────────────


def derive_and_check(
    db_path: str,
    strategy: str,
    market: str,
    symbol: str,
    side: Side,
    bar_ts: datetime | str | None = None,
    nonce: int = 0,
) -> tuple[str, str, bool, str | None]:
    """
    One-shot helper for writers: derive ids + dedupe-check.

    Returns:
        (client_order_id, correlation_id, existed, prior_trade_id)

    Caller pattern:
        cli_id, corr_id, existed, prior = derive_and_check(...)
        if existed:
            log.warning("DUPLICATE intent suppressed: %s → trade=%s", cli_id, prior)
            return prior
        record_trade(..., client_order_id=cli_id, correlation_id=corr_id, ...)
    """
    cli_id = make_client_order_id(strategy, market, symbol, side, bar_ts, nonce)
    corr_id = make_correlation_id()
    existed, prior = dedupe_check(db_path, cli_id)
    return cli_id, corr_id, existed, prior
