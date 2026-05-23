"""Idempotent paper_trades.db schema bootstrap. Runs inside aaats-paper-crypto container.

Schema must match execution/paper_trader._CREATE_SQL one-for-one. The
2026-05-23 phantom-ENA incident was caused by `value` and `risk_action`
being present in paper_trader's CREATE but missing here. When a fresh
DB was created by init_db FIRST (post-reset), the partial table blocked
every record_trade INSERT with "no such column: value" — see
tests/test_orphan_position_prevention.py for the regression pin.

paper_trader._MIGRATE_SQLS also includes additive ALTERs for both
columns; the two together heal any partial state. But init_db should
still create a complete schema so the migration path stays a safety
net, not a correctness requirement.
"""
import sqlite3, os, sys

DB = "/app/data/paper_trades.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    market TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    shares REAL,
    price REAL,
    value REAL DEFAULT 0.0,
    risk_action TEXT DEFAULT 'ALLOW',
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
CREATE INDEX IF NOT EXISTS idx_paper_trades_ts ON paper_trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_paper_trades_strategy ON paper_trades(strategy);
CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol ON paper_trades(symbol);
"""


def main():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.commit()
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"Tables: {tables}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
