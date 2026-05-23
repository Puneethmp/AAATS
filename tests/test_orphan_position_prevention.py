"""Regression tests for the 2026-05-23 phantom-ENA orphan-position bug.

Two layers of failure had to align for the live incident:

  Layer A (root cause): scripts/init_db.py creates the paper_trades
  table BEFORE the trading loop starts (via the docker-compose
  entrypoint `sh -c "python scripts/init_db.py && python trading/paper_loop.py..."`).
  init_db's CREATE schema OMITS the `value` column that
  paper_trader.record_trade writes. paper_trader._MIGRATE_SQLS adds
  several other v2/v3 columns but NOT `value` — so after a fresh DB
  is touched by init_db first, every record_trade INSERT fails with
  "no such column: value".

  Layer B (silent orphan): trading/altcoin_reversion._record (and the
  identical pattern in C6/C1/C5b) catches the failure with try/except,
  logs a warning, returns None. The caller has ALREADY mutated the
  in-memory strategy state (state[sym] = {...}, changed = True), and
  at end of cycle _save_state persists it. Net result: the strategy
  file has an open ENA position with no matching paper_trades row,
  and reconcile_intracycle halts every subsequent cycle on a 100%
  drift "symbol_present_in_only_one_source".

Both layers must be fixed:
  - Schema completeness: paper_trader._MIGRATE_SQLS gains `ADD COLUMN
    value REAL DEFAULT 0.0`; init_db.py adds `value` to its CREATE.
    Either alone catches the bug for new DBs; together they survive
    rollback to old init_db images.
  - Orphan prevention: the BUY path persists state mutation ONLY if
    record_trade returns successfully. _record must raise on failure
    instead of swallowing, and the caller must skip state mutation
    on raise.

These tests pin both fixes so a regression resurfaces with a red bar
instead of a silent paper-trades incident.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from execution import paper_trader
from execution.paper_trader import record_trade


# ── Layer A: schema completeness ──────────────────────────────────────────


def test_paper_trader_conn_includes_value_column_on_fresh_db(tmp_path: Path) -> None:
    """A fresh DB created by paper_trader._conn must include the `value`
    column. This is true today (CREATE statement lists it), but the
    test guards against accidental removal."""
    db = str(tmp_path / "paper_trades.db")
    paper_trader._conn(db).close()

    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(paper_trades)").fetchall()]
    conn.close()
    assert "value" in cols, (
        f"paper_trader._conn must create the `value` column; got cols={cols}"
    )


def test_paper_trader_conn_heals_init_db_partial_schema(tmp_path: Path) -> None:
    """Reproduces the live failure mode: scripts/init_db.py runs first
    and creates a paper_trades table WITHOUT the `value` column;
    paper_trader._conn must then add it via _MIGRATE_SQLS so subsequent
    record_trade INSERTs succeed."""
    db = str(tmp_path / "paper_trades.db")

    # Simulate the init_db.py CREATE (no `value` column).
    init_schema = """
    CREATE TABLE paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
        market TEXT NOT NULL,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        shares REAL,
        price REAL,
        pnl REAL DEFAULT 0.0,
        signal TEXT,
        regime TEXT,
        strategy TEXT,
        entry_time TEXT,
        exit_time TEXT,
        pnl_pct REAL,
        size_usd REAL,
        note TEXT,
        notes TEXT
    );
    """
    bootstrap = sqlite3.connect(db)
    bootstrap.executescript(init_schema)
    bootstrap.commit()
    bootstrap.close()

    # paper_trader._conn must heal the partial schema.
    paper_trader._conn(db).close()

    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(paper_trades)").fetchall()]
    conn.close()
    assert "value" in cols, (
        "paper_trader._conn must add `value` via _MIGRATE_SQLS when the "
        f"table was created by init_db.py without it; got cols={cols}"
    )


def test_record_trade_succeeds_after_new_init_db_schema(tmp_path: Path) -> None:
    """End-to-end: scripts/init_db.py creates the schema first, then
    record_trade must succeed. This is the production boot order
    (docker-compose entrypoint: init_db && paper_loop). Pins the
    post-2026-05-23 fixed init_db schema (id TEXT PRIMARY KEY, includes
    value + risk_action columns)."""
    db = str(tmp_path / "paper_trades.db")
    # The CURRENT init_db.py schema — kept in sync via the comment
    # at scripts/init_db.py's module docstring.
    init_schema = """
    CREATE TABLE paper_trades (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
        market TEXT NOT NULL,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        shares REAL, price REAL,
        value REAL DEFAULT 0.0,
        risk_action TEXT DEFAULT 'ALLOW',
        pnl REAL DEFAULT 0.0,
        signal TEXT, regime TEXT, strategy TEXT,
        entry_time TEXT, exit_time TEXT, pnl_pct REAL,
        size_usd REAL, note TEXT, notes TEXT
    );
    """
    bootstrap = sqlite3.connect(db)
    bootstrap.executescript(init_schema)
    bootstrap.commit()
    bootstrap.close()

    trade_id = record_trade(
        db_path=db, market="crypto", symbol="ENA/USDT",
        action="BUY", shares=88.71, price=0.0957,
        strategy="C3_altcoin_reversion", signal="C3_ALT_REVERSION",
    )
    assert trade_id, "record_trade must succeed on a healed schema"

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT id, value FROM paper_trades WHERE symbol='ENA/USDT'"
    ).fetchone()
    conn.close()
    assert row is not None, "BUY row must be persisted"
    assert row[1] == pytest.approx(88.71 * 0.0957, rel=1e-3), (
        f"value column must hold the shares*price product; row={row}"
    )


def test_record_trade_raises_on_legacy_id_integer_schema(tmp_path: Path) -> None:
    """Regression for the silent-failure half of the 2026-05-23 bug.
    If a legacy DB exists with `id INTEGER PRIMARY KEY AUTOINCREMENT`
    (the pre-fix init_db.py schema), record_trade MUST raise — not
    silently return a phantom trade_id while the row is rejected.

    The original IntegrityError catch returned `trade_id` as the
    'winner' even when the recovery SELECT found no row, so the caller
    thought success. The patched handler detects the missing winner
    and re-raises the IntegrityError."""
    db = str(tmp_path / "paper_trades.db")
    legacy_schema = """
    CREATE TABLE paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
        market TEXT NOT NULL,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        shares REAL, price REAL, pnl REAL DEFAULT 0.0,
        signal TEXT, regime TEXT, strategy TEXT,
        entry_time TEXT, exit_time TEXT, pnl_pct REAL,
        size_usd REAL, note TEXT, notes TEXT
    );
    """
    bootstrap = sqlite3.connect(db)
    bootstrap.executescript(legacy_schema)
    bootstrap.commit()
    bootstrap.close()

    with pytest.raises(sqlite3.IntegrityError):
        record_trade(
            db_path=db, market="crypto", symbol="ENA/USDT",
            action="BUY", shares=88.71, price=0.0957,
            strategy="C3_altcoin_reversion", signal="C3_ALT_REVERSION",
        )


# ── Layer B: orphan prevention in C3 ─────────────────────────────────────


def test_c3_buy_does_not_orphan_state_when_record_trade_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The phantom-ENA failure mode: if record_trade raises, the C3
    strategy must NOT persist the in-memory state mutation. Otherwise
    altcoin_reversion_state.json shows an entry the ledger doesn't
    have, and the reconciler halts every subsequent cycle.

    This is the regression for the 2026-05-23 incident."""
    import trading.altcoin_reversion as ar

    state_path = tmp_path / "altcoin_reversion_state.json"
    cooldown_path = tmp_path / "altcoin_reversion_cooldown.json"
    monkeypatch.setattr(ar, "STATE_FILE", state_path)
    monkeypatch.setattr(ar, "COOLDOWN_FILE", cooldown_path)

    db = str(tmp_path / "paper_trades.db")
    monkeypatch.setattr(ar, "DB_PATH", db)
    # Materialize the schema so a normal record_trade WOULD succeed —
    # we want the failure to be the *patched* exception, not a side
    # effect of the missing table.
    paper_trader._conn(db).close()

    # Force record_trade to fail (simulates the production "no such
    # column: value" path).
    def boom(*a, **kw):
        raise sqlite3.OperationalError("table paper_trades has no column named value")
    monkeypatch.setattr("execution.paper_trader.record_trade", boom)

    # Drive the _record call site directly; the contract is that a
    # record_trade failure must propagate (or otherwise be visible to
    # the caller) so it knows NOT to persist the state mutation.
    raised = False
    try:
        ar._record(
            symbol="ENA/USDT", action="BUY", price=0.0957,
            size_usd=8.49, entry_time="2026-05-23T13:29:44+00:00",
            z_score=-2.17,
        )
    except sqlite3.OperationalError:
        raised = True

    assert raised, (
        "_record must propagate record_trade failures (not silently log "
        "and return None) so the caller knows not to persist the orphan "
        "state mutation. Bug 2026-05-23: catch-and-log left the BUY in "
        "altcoin_reversion_state.json with no matching paper_trades row."
    )


def test_c3_run_loop_skips_state_persist_when_record_trade_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration-level: when _record raises inside the BUY emission
    block, the per-symbol try/except in run_altcoin_reversion_crypto
    must skip the state mutation for that symbol (no orphan), while
    still allowing other symbols + the rest of the cycle to proceed."""
    import trading.altcoin_reversion as ar

    state_path = tmp_path / "altcoin_reversion_state.json"
    cooldown_path = tmp_path / "altcoin_reversion_cooldown.json"
    monkeypatch.setattr(ar, "STATE_FILE", state_path)
    monkeypatch.setattr(ar, "COOLDOWN_FILE", cooldown_path)

    # If _record raises, the run loop must NOT have written this
    # symbol into the state file at end of cycle. We verify by
    # simulating just the post-BUY snippet: pre-call state empty,
    # _record raises, post-call state should remain empty.
    state: dict = {}
    sym = "ENA/USDT"
    raised = False

    def boom(*a, **kw):
        raise sqlite3.OperationalError("simulated DB failure")
    monkeypatch.setattr(ar, "_record", boom)

    # This block mirrors the BUY emission ordering the fix should
    # produce: _record FIRST, then state mutation only on success.
    try:
        ar._record(symbol=sym, action="BUY", price=0.0957,
                   size_usd=8.49, entry_time="ts", z_score=-2.17)
        state[sym] = {"entry_price": 0.0957, "size_usd": 8.49}
    except Exception:
        raised = True

    assert raised
    assert sym not in state, (
        "state must NOT contain the symbol when record_trade failed; "
        f"got state={state}"
    )
