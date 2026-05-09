"""Idempotent paper_trades.db schema bootstrap. Runs inside aaats-paper-crypto container."""
import sqlite3, os, sys

DB = "/app/data/paper_trades.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_trades (
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
