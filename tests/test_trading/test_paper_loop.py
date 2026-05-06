"""Tests for trading/paper_loop.py."""

from __future__ import annotations

import sqlite3

import pytest

from risk.engine import RiskEngine
from trading.paper_loop import (
    PaperTradingState,
    Position,
    fetch_paper_trades,
    get_paper_summary,
    process_signal,
)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "trades.db")
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, market TEXT, symbol TEXT, action TEXT,
            shares INTEGER, price REAL, value REAL, signal TEXT,
            regime TEXT, risk_action TEXT, pnl REAL, note TEXT
        )
    """)
    conn.commit()
    return conn, path


@pytest.fixture
def engine():
    return RiskEngine(initial_portfolio=100_000)


@pytest.fixture
def state():
    s = PaperTradingState()
    s.capital = {"us": 50_000.0, "india": 30_000.0, "crypto": 20_000.0}
    return s


class TestProcessSignal:
    def test_buy_creates_position(self, db, engine, state):
        conn, _ = db
        process_signal("us", "AAPL", "BUY", 100.0, 5, "BULL_TREND", engine, state, conn, 50_000)
        assert len(state.positions["us"]) == 1
        assert state.positions["us"][0].symbol == "AAPL"

    def test_buy_logs_trade(self, db, engine, state):
        conn, path = db
        process_signal("us", "AAPL", "BUY", 100.0, 5, "BULL_TREND", engine, state, conn, 50_000)
        rows = conn.execute("SELECT * FROM paper_trades").fetchall()
        assert len(rows) == 1

    def test_sell_closes_position(self, db, engine, state):
        conn, _ = db
        # Open a position first
        state.positions["us"].append(Position("AAPL", "us", 5, 100.0, "2024-01-01"))
        process_signal("us", "AAPL", "SELL", 110.0, 0, "BEAR_TREND", engine, state, conn, 50_000)
        assert len(state.positions["us"]) == 0

    def test_sell_logs_pnl(self, db, engine, state):
        conn, _ = db
        state.positions["us"].append(Position("AAPL", "us", 5, 100.0, "2024-01-01"))
        process_signal("us", "AAPL", "SELL", 110.0, 0, None, engine, state, conn, 50_000)
        rows = conn.execute("SELECT pnl FROM paper_trades WHERE action='SELL'").fetchall()
        assert rows[0][0] == pytest.approx(50.0)  # (110-100)*5

    def test_hold_does_nothing(self, db, engine, state):
        conn, _ = db
        process_signal("us", "AAPL", "HOLD", 100.0, 5, None, engine, state, conn, 50_000)
        rows = conn.execute("SELECT * FROM paper_trades").fetchall()
        assert len(rows) == 0
        assert len(state.positions["us"]) == 0

    def test_buy_blocked_by_risk_engine(self, db, engine, state):
        conn, _ = db
        engine.update_portfolio(79_000)  # trigger halt all
        decision = process_signal("us", "AAPL", "BUY", 100.0, 5, None, engine, state, conn, 50_000)
        assert decision.action == "HALT_ALL"
        assert len(state.positions["us"]) == 0

    def test_trade_count_increments(self, db, engine, state):
        conn, _ = db
        assert state.trade_count == 0
        process_signal("us", "AAPL", "BUY", 100.0, 5, None, engine, state, conn, 50_000)
        assert state.trade_count == 1


class TestFetchPaperTrades:
    def test_returns_empty_when_no_db(self, tmp_path):
        df = fetch_paper_trades(str(tmp_path / "nonexistent.db"))
        assert df.empty

    def test_returns_all_trades(self, db):
        conn, path = db
        conn.execute(
            "INSERT INTO paper_trades VALUES (NULL,'2024-01-01','us','AAPL','BUY',5,100.0,500.0,'BUY','BULL_TREND','ALLOW',NULL,NULL)"
        )
        conn.commit()
        df = fetch_paper_trades(path)
        assert len(df) == 1

    def test_market_filter(self, db):
        conn, path = db
        conn.executemany(
            "INSERT INTO paper_trades VALUES (NULL,?,'us','AAPL','BUY',5,100.0,500.0,'BUY',NULL,'ALLOW',NULL,NULL)",
            [("2024-01-01",), ("2024-01-02",)]
        )
        conn.execute(
            "INSERT INTO paper_trades VALUES (NULL,'2024-01-03','india','RELIANCE','BUY',10,500.0,5000.0,'BUY',NULL,'ALLOW',NULL,NULL)"
        )
        conn.commit()
        df = fetch_paper_trades(path, market="us")
        assert len(df) == 2


class TestGetPaperSummary:
    def test_empty_returns_zeros(self, tmp_path):
        summary = get_paper_summary(str(tmp_path / "nonexistent.db"))
        assert summary["total_trades"] == 0
        assert summary["total_pnl"] == 0.0

    def test_pnl_aggregated(self, db):
        conn, path = db
        conn.executemany(
            "INSERT INTO paper_trades VALUES (NULL,'2024-01-01','us','AAPL','SELL',5,110.0,550.0,'SELL',NULL,'ALLOW',?,NULL)",
            [(50.0,), (30.0,), (-10.0,)]
        )
        conn.commit()
        summary = get_paper_summary(path)
        assert summary["total_pnl"] == pytest.approx(70.0)

    def test_win_rate_calculated(self, db):
        conn, path = db
        conn.executemany(
            "INSERT INTO paper_trades VALUES (NULL,'2024-01-01','us','AAPL','SELL',5,110.0,550.0,'SELL',NULL,'ALLOW',?,NULL)",
            [(50.0,), (30.0,), (-10.0,)]
        )
        conn.commit()
        summary = get_paper_summary(path)
        assert summary["win_rate"] == pytest.approx(2/3)
