"""
Regression tests for the 2026-05-25 portfolio-stats reconcile fix.

The bug: C3 (altcoin_reversion) and C6 (bollinger_range) write trades to
paper_trades.db but DO NOT increment portfolio["total_trades"] /
realized_pnl / wins / losses. Observed 2026-05-25: paper_portfolio.crypto.
total_trades = 8 (only C1's 4 pair-trades × 2); DB had 20 trades.

The fix: trading.live_paper_runner._reconcile_portfolio_stats_from_db()
derives those four fields from the DB at end of every cycle, so any
strategy that forgets bookkeeping is auto-corrected.

These tests verify:
  T1. Reconciler refreshes total_trades, realized_pnl, wins, losses
      to match the DB.
  T2. Reconciler does NOT touch `capital` (strategies own that).
  T3. Reconciler does NOT touch `starting_equity` (set once by reset script).
  T4. Idempotency — calling twice produces the same result.
  T5. Per-market isolation — crypto reconcile does not affect india fields.
  T6. Empty DB / market with no trades — fields zero out cleanly.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


CREATE_SQL = (
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


def _seed_db(db_path: Path, rows: list[tuple]) -> None:
    """rows = [(market, symbol, action, pnl, pnl_pct), ...]"""
    conn = sqlite3.connect(db_path)
    conn.execute(CREATE_SQL)
    for i, (mkt, sym, action, pnl, pnl_pct) in enumerate(rows):
        conn.execute(
            "INSERT INTO paper_trades "
            "(id, timestamp, market, symbol, action, shares, price, value, "
            " signal, regime, risk_action, pnl, note, strategy, entry_time, "
            " exit_time, pnl_pct, notes, size_usd) "
            "VALUES (?, ?, ?, ?, ?, 1.0, 100.0, 100.0, 'SIG', 'R', 'ALLOW', "
            "?, '', 'TEST', '', '', ?, '', 0.0)",
            (f"id-{i}", f"2026-05-25T00:00:{i:02d}Z", mkt, sym, action, pnl, pnl_pct),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def runner_module(tmp_path, monkeypatch):
    """
    Import live_paper_runner with DB_PATH and PORTFOLIO_FILE redirected to
    tmp_path so the test never touches real state.
    """
    db_path = tmp_path / "paper_trades.db"
    portfolio_file = tmp_path / "paper_portfolio.json"
    positions_file = tmp_path / "paper_positions.json"
    log_file = tmp_path / "paper_runner.log"
    (tmp_path / "logs").mkdir(exist_ok=True)

    # Point the runner constants at tmp paths BEFORE importing the module
    # for the first time. The module captures these into module-level
    # constants at import; we monkeypatch the values after import too.
    import importlib

    if "trading.live_paper_runner" in sys.modules:
        del sys.modules["trading.live_paper_runner"]
    runner = importlib.import_module("trading.live_paper_runner")

    monkeypatch.setattr(runner, "DB_PATH", str(db_path))
    monkeypatch.setattr(runner, "PORTFOLIO_FILE", portfolio_file)
    monkeypatch.setattr(runner, "POSITIONS_FILE", positions_file)
    monkeypatch.setattr(runner, "LOG_FILE", log_file)
    return runner, db_path


def _baseline_portfolio() -> dict:
    return {
        "crypto": {
            "capital": 101.0,
            "starting_equity": 200.0,
            "realized_pnl": 999.0,  # deliberately wrong to verify overwrite
            "total_trades": 999,
            "wins": 999,
            "losses": 999,
            "total_win_pct": 999.0,
            "total_loss_pct": 999.0,
            "settlement_queue": [],
        },
        "india": {
            "capital": 25000.0,
            "starting_equity": 25000.0,
            "realized_pnl": 555.0,
            "total_trades": 555,
            "wins": 555,
            "losses": 555,
            "total_win_pct": 555.0,
            "total_loss_pct": 555.0,
            "settlement_queue": [],
        },
    }


def test_t1_reconciler_refreshes_stats_from_db(runner_module):
    """T1: total_trades / realized_pnl / wins / losses match DB."""
    runner, db_path = runner_module
    # 4 C1 pair entries (pnl=0 on BUY) + 4 C1 pair exits (pnl=+0.01 each)
    # + 3 C3 BUYs (pnl=0) + 5 C6 BUYs (pnl=0) + 4 C6 SELLs (one -0.10,
    # rest -0.02). Total = 4+4+3+5+4 = 20 rows. (4 BUY rows + 4 wins
    # ($0.01 each) for C1 stat_arb pair-exits; 0 wins / 4 losses for C6.)
    rows = []
    for i in range(4):
        rows.append(("crypto", f"BTC{i}", "BUY", 0.0, 0.0))
    for i in range(4):
        # pair-exit row: pnl=+0.01 win
        rows.append(("crypto", f"BTC{i}", "SELL", 0.01, 1.0))
    for i in range(3):
        rows.append(("crypto", f"ALT{i}", "BUY", 0.0, 0.0))
    for i in range(5):
        rows.append(("crypto", f"BLG{i}", "BUY", 0.0, 0.0))
    rows.append(("crypto", "BLG0", "SELL", -0.10, -3.0))
    for i in range(3):
        rows.append(("crypto", f"BLG{i+1}", "SELL", -0.02, -0.8))

    _seed_db(db_path, rows)
    portfolio = _baseline_portfolio()
    runner._reconcile_portfolio_stats_from_db(portfolio, "crypto")
    p = portfolio["crypto"]

    assert p["total_trades"] == 20, f"expected 20 trades, got {p['total_trades']}"
    # realized PnL = 4 × 0.01 + (-0.10) + 3 × (-0.02) = 0.04 - 0.16 = -0.12
    assert p["realized_pnl"] == pytest.approx(-0.12, abs=1e-9)
    assert p["wins"] == 4
    assert p["losses"] == 4
    # win_pct fractions: 4 × 1.0% = 0.04
    assert p["total_win_pct"] == pytest.approx(0.04, abs=1e-9)
    # loss_pct fractions: 1 × 3.0% + 3 × 0.8% = 0.054
    assert p["total_loss_pct"] == pytest.approx(0.054, abs=1e-9)


def test_t2_capital_untouched(runner_module):
    """T2: capital is strategy-owned; reconciler must not touch it."""
    runner, db_path = runner_module
    _seed_db(db_path, [("crypto", "BTC", "SELL", 5.0, 2.5)])
    portfolio = _baseline_portfolio()
    portfolio["crypto"]["capital"] = 42.0
    runner._reconcile_portfolio_stats_from_db(portfolio, "crypto")
    assert portfolio["crypto"]["capital"] == 42.0


def test_t3_starting_equity_untouched(runner_module):
    """T3: starting_equity set once by reset script; reconciler must not touch."""
    runner, db_path = runner_module
    _seed_db(db_path, [("crypto", "BTC", "SELL", 5.0, 2.5)])
    portfolio = _baseline_portfolio()
    portfolio["crypto"]["starting_equity"] = 200.0
    runner._reconcile_portfolio_stats_from_db(portfolio, "crypto")
    assert portfolio["crypto"]["starting_equity"] == 200.0


def test_t4_idempotent(runner_module):
    """T4: calling twice produces same result."""
    runner, db_path = runner_module
    _seed_db(
        db_path,
        [
            ("crypto", "BTC", "BUY", 0.0, 0.0),
            ("crypto", "BTC", "SELL", 3.0, 1.5),
        ],
    )
    portfolio = _baseline_portfolio()
    runner._reconcile_portfolio_stats_from_db(portfolio, "crypto")
    snap1 = dict(portfolio["crypto"])
    runner._reconcile_portfolio_stats_from_db(portfolio, "crypto")
    snap2 = dict(portfolio["crypto"])
    assert snap1 == snap2


def test_t5_per_market_isolation(runner_module):
    """T5: reconciling crypto must not touch india fields."""
    runner, db_path = runner_module
    _seed_db(db_path, [("crypto", "BTC", "SELL", 3.0, 1.5)])
    portfolio = _baseline_portfolio()
    india_snap = dict(portfolio["india"])
    runner._reconcile_portfolio_stats_from_db(portfolio, "crypto")
    assert portfolio["india"] == india_snap


def test_t6_empty_db_no_trades(runner_module):
    """T6: market with no trades zeros stats (not 999 carryover)."""
    runner, db_path = runner_module
    _seed_db(db_path, [])  # creates empty table
    portfolio = _baseline_portfolio()
    runner._reconcile_portfolio_stats_from_db(portfolio, "crypto")
    p = portfolio["crypto"]
    assert p["total_trades"] == 0
    assert p["realized_pnl"] == 0.0
    assert p["wins"] == 0
    assert p["losses"] == 0
    assert p["total_win_pct"] == 0.0
    assert p["total_loss_pct"] == 0.0


def test_t7_missing_db_noop(runner_module):
    """T7: DB file doesn't exist (fresh box) → no-op, no crash."""
    runner, db_path = runner_module
    # Do NOT create the DB
    assert not db_path.exists()
    portfolio = _baseline_portfolio()
    # Snapshot to compare
    crypto_before = dict(portfolio["crypto"])
    runner._reconcile_portfolio_stats_from_db(portfolio, "crypto")
    # Stats unchanged when DB missing (defensive)
    assert portfolio["crypto"] == crypto_before
