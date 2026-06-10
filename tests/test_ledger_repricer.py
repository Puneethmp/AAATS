"""Tests for analytics.ledger_repricer — honest re-pricing + no-trade baseline."""

from __future__ import annotations

import sqlite3

import pytest

from analytics import ledger_repricer as lr


def _make_db(tmp_path, rows):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE paper_trades (id TEXT, timestamp TEXT, market TEXT, symbol TEXT, "
        "action TEXT, shares REAL, price REAL, value REAL, pnl REAL, strategy TEXT, "
        "exit_time TEXT, pnl_pct REAL, size_usd REAL, note TEXT, notes TEXT)"
    )
    for i, r in enumerate(rows):
        conn.execute(
            "INSERT INTO paper_trades (id,timestamp,market,symbol,action,shares,price,"
            "value,pnl,strategy,size_usd,note,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(i),
                r.get("ts", f"2026-06-0{i + 1}T00:00:00+00:00"),
                "crypto",
                r.get("symbol", "X/USDT"),
                r.get("action", "SELL"),
                1.0,
                100.0,
                r.get("size", 100.0),
                r.get("pnl", 0.0),
                r.get("strategy", "C3"),
                r.get("size", 100.0),
                r.get("note", ""),
                r.get("notes", "{}"),
            ),
        )
    conn.commit()
    conn.close()
    return str(db)


def test_no_trade_baseline_is_zero():
    assert lr.no_trade_baseline() == 0.0


def test_only_realized_events_counted(tmp_path):
    db = _make_db(tmp_path, [{"pnl": 0.0}, {"pnl": 0.5}, {"pnl": -0.3}])
    rep = lr.reprice_ledger(db, slippage_bps=10.0)
    assert rep.n_events == 2  # the pnl==0 row is an open leg, excluded


def test_net_is_below_gross_when_costs_applied(tmp_path):
    db = _make_db(tmp_path, [{"pnl": 1.0, "size": 100.0}])
    rep = lr.reprice_ledger(db, slippage_bps=10.0)
    # round-trip cost on $100 spot taker + 10bps slip = 0.40
    assert rep.total_gross == pytest.approx(1.0)
    assert rep.total_net == pytest.approx(0.60)


def test_marginal_gross_winner_becomes_cost_bucket(tmp_path):
    db = _make_db(tmp_path, [{"pnl": 0.10, "size": 100.0}])
    rep = lr.reprice_ledger(db, slippage_bps=10.0)
    assert "COST" in rep.buckets
    assert rep.beats_no_trade() is False


def test_signal_vs_risk_bucketing(tmp_path):
    db = _make_db(
        tmp_path,
        [
            {
                "pnl": -0.05,
                "notes": '{"exit_reason": "regime_flip"}',
            },  # small loss, no stop -> SIGNAL
            {
                "pnl": -0.80,
                "notes": '{"exit_reason": "z_hard_stop"}',
            },  # big stop-out -> RISK
        ],
    )
    rep = lr.reprice_ledger(db, slippage_bps=10.0)
    assert rep.buckets["SIGNAL"]["n"] == 1
    assert rep.buckets["RISK"]["n"] == 1


def test_beats_no_trade_only_when_net_positive(tmp_path):
    winners = _make_db(tmp_path, [{"pnl": 5.0, "size": 100.0}])
    rep = lr.reprice_ledger(winners, slippage_bps=10.0)
    assert rep.beats_no_trade() is True


def test_buy_and_hold_reference():
    # buy $100 at 100, exit at 110 => ~+$10 gross minus ~2 fees
    pnl = lr.buy_and_hold_pnl(100.0, 110.0, 100.0)
    assert 9.0 < pnl < 10.0
