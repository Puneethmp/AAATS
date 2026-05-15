"""
tests/test_reconcile_denylist.py — verify deny-list filter at the reconciler

Regression coverage: PENGU and LUNC remained on the kill-switch radar after
they were removed from the trading universe, because the reconciler still
saw their orphan ledger rows in paper_trades.db. This test seeds exactly
those rows and asserts that no HALT or WARN drift issues are emitted.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import scripts.reconcile_intracycle as recon


@pytest.fixture
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a paper_trades.db with PENGU & LUNC orphan BUY rows."""
    db_path = tmp_path / "paper_trades.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE paper_trades ("
        "id TEXT PRIMARY KEY, timestamp TEXT, market TEXT, symbol TEXT, "
        "action TEXT, shares REAL, price REAL, value REAL, "
        "signal TEXT, regime TEXT, risk_action TEXT, pnl REAL DEFAULT 0.0, "
        "note TEXT, strategy TEXT DEFAULT ''"
        ")"
    )
    rows = [
        ("1", "2026-05-10T00:00:00Z", "crypto", "PENGU/USDT", "BUY",
         1000.0, 0.012, 12.0, "BUY", "RANGE_BOUND", "ALLOW", 0.0, "", "C3"),
        ("2", "2026-05-10T00:00:00Z", "crypto", "LUNC/USDT", "BUY",
         500000.0, 0.00009, 45.0, "BUY", "RANGE_BOUND", "ALLOW", 0.0, "", "C3"),
        # A clean symbol that should still pass cleanly (no drift since both
        # sources will be empty).
        ("3", "2026-05-10T00:00:00Z", "crypto", "BTC/USDT", "BUY",
         0.0001, 60000.0, 6.0, "BUY", "TRENDING", "ALLOW", 0.0, "", "C3"),
        ("4", "2026-05-10T01:00:00Z", "crypto", "BTC/USDT", "SELL",
         0.0001, 60500.0, 6.05, "SELL", "TRENDING", "ALLOW", 0.05, "", "C3"),
    ]
    conn.executemany(
        "INSERT INTO paper_trades "
        "(id, timestamp, market, symbol, action, shares, price, value, "
        " signal, regime, risk_action, pnl, note, strategy) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    # Redirect both the file paths the reconciler reads and the kill-switch.
    monkeypatch.setattr(recon, "DB_PATH", db_path)
    monkeypatch.setattr(recon, "POSITIONS_FILE", tmp_path / "paper_positions.json")
    monkeypatch.setattr(recon, "PORTFOLIO_FILE", tmp_path / "paper_portfolio.json")

    # Strategy state directory must exist but be empty so Source A is empty.
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(recon, "_ROOT", tmp_path)

    return db_path


def test_pengu_and_lunc_do_not_halt(seeded_db: Path) -> None:
    """PENGU and LUNC orphan rows must be skipped, not halt the reconciler."""
    result = recon.reconcile_now(halt_on_critical=False, markets=["crypto"])

    # No issues at all should mention PENGU or LUNC.
    halting_symbols = [i.symbol for i in result.issues if i.severity == "HALT"]
    warning_symbols = [i.symbol for i in result.issues if i.severity == "WARN"]

    assert not any("PENGU" in s for s in halting_symbols + warning_symbols), (
        f"PENGU should be deny-listed — got issues: {result.issues}"
    )
    assert not any("LUNC" in s for s in halting_symbols + warning_symbols), (
        f"LUNC should be deny-listed — got issues: {result.issues}"
    )
    assert not result.halted


def test_denied_symbol_helper() -> None:
    """The helper itself returns True for known deny-listed bases."""
    assert recon._is_denied_symbol("crypto", "PENGU/USDT") is True
    assert recon._is_denied_symbol("crypto", "LUNC/USDT") is True
    # Non-crypto markets are never deny-listed by this helper.
    assert recon._is_denied_symbol("india", "PENGU") is False
    # Symbols that pass the universe filter must NOT be denied.
    assert recon._is_denied_symbol("crypto", "BTC/USDT") is False
    assert recon._is_denied_symbol("crypto", "ETH/USDT") is False
