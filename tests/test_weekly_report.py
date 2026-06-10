"""Tests for the weekly honest-PnL report generator."""

from __future__ import annotations

import sqlite3

from tools.reports.weekly_report import generate


def _db(tmp_path, rows):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE paper_trades (id TEXT, timestamp TEXT, market TEXT, symbol TEXT, "
        "action TEXT, shares REAL, price REAL, value REAL, pnl REAL, strategy TEXT, "
        "exit_time TEXT, pnl_pct REAL, size_usd REAL, note TEXT, notes TEXT)"
    )
    for i, r in enumerate(rows):
        conn.execute(
            "INSERT INTO paper_trades (id,timestamp,market,symbol,action,value,pnl,strategy,"
            "size_usd,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(i),
                f"2026-06-0{i + 1}T00:00:00+00:00",
                "crypto",
                "X/USDT",
                "SELL",
                r.get("size", 100.0),
                r.get("pnl", 0.0),
                r.get("strategy", "C3"),
                r.get("size", 100.0),
                r.get("notes", "{}"),
            ),
        )
    conn.commit()
    conn.close()
    return str(db)


def test_report_never_reports_gross_as_headline(tmp_path):
    db = _db(tmp_path, [{"pnl": 0.10, "size": 100.0}])
    md = generate(db, 1, None, None)
    assert "NET of fees" in md
    assert "No-trade baseline" in md
    # marginal winner must show as NOT beating no-trade
    assert "Beats no-trade? | NO" in md


def test_report_shows_baseline_gap(tmp_path):
    db = _db(tmp_path, [{"pnl": -1.0, "size": 100.0}])
    md = generate(db, 2, None, None)
    assert "Gap vs no-trade" in md
    assert "demotion" in md  # losing week => demotion language


def test_winning_week_beats_baseline(tmp_path):
    db = _db(tmp_path, [{"pnl": 10.0, "size": 100.0}])
    md = generate(db, 3, None, None)
    assert "Beats no-trade? | YES" in md
