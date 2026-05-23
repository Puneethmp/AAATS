"""
tests/test_reconciler_c1_exclusion.py — Option A of the BTC/ETH ledger drift fix.

Pre-fix behavior (recorded in docs/known_issues/2026-05-23_btc_eth_ledger_drift.md):
  C1_stat_arb writes leg trades into paper_trades.db with the same schema as
  any other strategy (BUY one symbol, SELL another). Its canonical position
  state, however, lives in data/stat_arb_state.json keyed by a pair string
  ("BTC/USDT_ETH/USDT") that the reconciler's Source-A loader cannot parse —
  so Source A reports zero positions while Source B sees the open legs. The
  reconciler then emits HALT-severity `symbol_present_in_only_one_source`
  drift on the leg symbols (BTC, ETH).

Option A fix: exclude C1_stat_arb from Source B (parity with C5b_funding_arb,
the other delta-neutral arb strategy whose legs are already excluded).

This test seeds a synthetic open C1 pair (BUY BTC, SELL ETH) in a tmp
paper_trades.db and asserts the reconciler PASSES (no HALT issues), even
though Source A is empty and the legs net to non-zero shares.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import scripts.reconcile_intracycle as recon


@pytest.fixture
def c1_open_pair_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    A paper_trades.db with an open C1 stat-arb pair and nothing else:
      - C1 BUY 0.0001 BTC/USDT @ 70000 (long leg)
      - C1 SELL 0.003 ETH/USDT @ 2100 (short leg)

    Pre-fix this produces two HALT-severity drift issues (BTC and ETH each
    present only in Source B). Post-fix the C1 strategy rows are excluded
    from Source B; both leg symbols disappear and the reconciler passes.
    """
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
        # C1 stat-arb LONG_A entry — BUY BTC leg, SELL ETH leg, same cycle.
        ("c1-buy", "2026-05-22T15:41:18Z", "crypto", "BTC/USDT", "BUY",
         0.0001, 70000.0, 7.0, "BUY", "TRENDING", "ALLOW", 0.0,
         "stat_arb LONG_A leg A", "C1_stat_arb"),
        ("c1-sell", "2026-05-22T15:41:18Z", "crypto", "ETH/USDT", "SELL",
         0.003, 2100.0, 6.3, "SELL", "TRENDING", "ALLOW", 0.0,
         "stat_arb LONG_A leg B", "C1_stat_arb"),
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

    monkeypatch.setattr(recon, "DB_PATH", db_path)
    monkeypatch.setattr(recon, "POSITIONS_FILE", tmp_path / "paper_positions.json")
    monkeypatch.setattr(recon, "PORTFOLIO_FILE", tmp_path / "paper_portfolio.json")
    # Source A must resolve to an empty dir so it produces no positions —
    # mirrors the real bug where stat_arb_state.json's pair-keyed entry
    # is silently skipped.
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(recon, "_ROOT", tmp_path)

    return db_path


def test_c1_stat_arb_legs_do_not_halt(c1_open_pair_db: Path) -> None:
    """An open C1 BTC+ETH pair must not trigger HALT drift."""
    result = recon.reconcile_now(halt_on_critical=False, markets=["crypto"])

    halt_issues = [i for i in result.issues if i.severity == "HALT"]
    warn_issues = [i for i in result.issues if i.severity == "WARN"]

    assert not halt_issues, (
        "C1 leg trades must be excluded from Source B "
        f"(Option A of docs/known_issues/2026-05-23_btc_eth_ledger_drift.md); "
        f"got HALT drift: {halt_issues}"
    )
    assert not warn_issues, f"unexpected WARN drift: {warn_issues}"
    assert not result.halted, "reconciler should pass with C1 legs excluded"


def test_source_b_excludes_c1_rows(c1_open_pair_db: Path) -> None:
    """Source B must report empty crypto positions when only C1 legs exist."""
    state_b = recon._compute_positions_from_db()
    assert "BTC/USDT" not in state_b.get("crypto", {}), (
        f"BTC/USDT should be excluded from Source B; got {state_b}"
    )
    assert "ETH/USDT" not in state_b.get("crypto", {}), (
        f"ETH/USDT should be excluded from Source B; got {state_b}"
    )


def test_non_c1_strategies_still_visible_in_source_b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A regular C3 BUY must remain visible in Source B (regression guard)."""
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
    conn.execute(
        "INSERT INTO paper_trades VALUES "
        "('c3-buy', '2026-05-22T10:00:00Z', 'crypto', 'ADA/USDT', 'BUY', "
        "60.0, 0.25, 15.0, 'BUY', 'RANGE_BOUND', 'ALLOW', 0.0, '', "
        "'C3_altcoin_reversion')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(recon, "DB_PATH", db_path)

    state_b = recon._compute_positions_from_db()
    assert state_b.get("crypto", {}).get("ADA/USDT") == 60.0, (
        f"C3 BUY should remain visible in Source B; got {state_b}"
    )
