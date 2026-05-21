"""Tests for scripts/migrate_positions_to_db.py  -- B2 of unified ledger.

Uses a tmp_path fixture paper_trades.db with known state files to exercise:
  - BUY-row lookup heals exit-sizing residuals (real shares != size/price).
  - Fallback when no BUY row within +/-5min.
  - State files renamed to <name>.migrated_2026-05-21.
  - Empty state files renamed (idempotency primitive).
  - cooldown / halt_state files excluded.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3

import pytest

from foundation import positions
from scripts import migrate_positions_to_db as mig


@pytest.fixture
def tmp_db(tmp_path):
    """Fresh paper_trades.db with the production schema + the positions table."""
    db_path = str(tmp_path / "paper_trades.db")
    # Materialise paper_trades using production schema.
    from execution import paper_trader
    paper_trader._conn(db_path).close()
    # Materialise positions table via our API.
    positions._conn(db_path).close()
    return db_path


def _insert_buy(
    db_path: str,
    strategy: str,
    symbol: str,
    shares: float,
    price: float,
    timestamp: str,
    market: str = "crypto",
) -> None:
    """Insert a BUY row directly (bypasses paper_trader.record_trade idempotency)."""
    import uuid
    c = sqlite3.connect(db_path)
    c.execute(
        "INSERT INTO paper_trades ("
        "id, timestamp, market, symbol, action, shares, price, value, "
        "signal, regime, risk_action, pnl, note, strategy, entry_time"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()), timestamp, market, symbol, "BUY",
            shares, price, shares * price, "TEST", "RANGE", "ALLOW",
            0.0, "test BUY", strategy, timestamp,
        ),
    )
    c.commit()
    c.close()


def test_migrate_uses_buy_row_shares_when_match_found(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # State file says size_usd=10 entry_price=100 -> naive 0.1 shares,
    # but the real BUY row has 0.097 (e.g. fee impact / partial fill).
    state_file = data_dir / "altcoin_reversion_state.json"
    state_file.write_text(json.dumps({
        "SOL/USDT": {
            "entry_price": 100.0,
            "entry_ts": "2026-05-21T01:00:00+00:00",
            "size_usd": 10.0,
            "entry_z": -1.8,
        }
    }))

    _insert_buy(
        tmp_db, "C3_altcoin_reversion", "SOL/USDT",
        shares=0.097,
        price=100.0,
        timestamp="2026-05-21T01:00:30+00:00",   # 30s after entry_ts
    )

    summary = mig.migrate(data_dir=data_dir, db_path=tmp_db)
    assert summary["inserted_rows"] == 1
    assert summary["fallbacks"] == []

    row = positions.get_position(
        "C3_altcoin_reversion", "SOL/USDT", db_path=tmp_db
    )
    assert row is not None
    assert row["entry_shares"] == pytest.approx(0.097)
    assert row["metadata"] == {"entry_z": -1.8}


def test_migrate_falls_back_to_size_over_price_when_no_buy_match(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    state_file = data_dir / "bollinger_range_state.json"
    state_file.write_text(json.dumps({
        "BTC/USDT": {
            "entry_price": 50.0,
            "entry_ts": "2026-05-21T02:00:00+00:00",
            "size_usd": 6.0,
            "entry_pct_b": 0.1,
        }
    }))
    # BUY row is 10 minutes off -- outside the +/-5min window.
    _insert_buy(
        tmp_db, "C6_bollinger_range", "BTC/USDT",
        shares=0.12,
        price=50.0,
        timestamp="2026-05-21T02:10:00+00:00",
    )

    summary = mig.migrate(data_dir=data_dir, db_path=tmp_db)
    assert summary["inserted_rows"] == 1
    assert len(summary["fallbacks"]) == 1
    assert "no-BUY-match" in summary["fallbacks"][0]

    row = positions.get_position(
        "C6_bollinger_range", "BTC/USDT", db_path=tmp_db
    )
    assert row is not None
    # Fallback path: size_usd / entry_price = 6 / 50 = 0.12 (coincidence
    # with the out-of-window BUY row's quantity is irrelevant; the row
    # came from the formula, not the BUY).
    assert row["entry_shares"] == pytest.approx(0.12)


def test_migrate_renames_state_files(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    state_file = data_dir / "stat_arb_state.json"
    state_file.write_text(json.dumps({
        "ETH/USDT": {
            "entry_price": 200.0,
            "entry_ts": "2026-05-21T00:00:00+00:00",
            "size_usd": 12.0,
        }
    }))

    mig.migrate(data_dir=data_dir, db_path=tmp_db,
                rename_suffix=".migrated_TEST")

    assert not state_file.exists()
    assert (data_dir / "stat_arb_state.json.migrated_TEST").exists()


def test_migrate_empty_state_file_is_renamed(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "stat_arb_state.json").write_text("{}")

    summary = mig.migrate(data_dir=data_dir, db_path=tmp_db,
                          rename_suffix=".migrated_TEST")
    assert summary["inserted_rows"] == 0
    assert (data_dir / "stat_arb_state.json.migrated_TEST").exists()


def test_migrate_excludes_cooldown_and_halt(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "altcoin_reversion_cooldown.json").write_text(
        json.dumps({"SOL/USDT": "2026-05-22T00:00:00+00:00"})
    )
    (data_dir / "halt_state.json").write_text("{}")
    (data_dir / "altcoin_reversion_state.json").write_text(json.dumps({
        "SOL/USDT": {
            "entry_price": 100.0,
            "entry_ts": "2026-05-21T01:00:00+00:00",
            "size_usd": 10.0,
        }
    }))

    summary = mig.migrate(data_dir=data_dir, db_path=tmp_db,
                          rename_suffix=".migrated_TEST")
    assert summary["inserted_rows"] == 1
    # cooldown / halt files still present, untouched
    assert (data_dir / "altcoin_reversion_cooldown.json").exists()
    assert (data_dir / "halt_state.json").exists()


def test_migrate_dry_run_does_not_insert_or_rename(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    state_file = data_dir / "altcoin_reversion_state.json"
    state_file.write_text(json.dumps({
        "SOL/USDT": {
            "entry_price": 100.0, "entry_ts": "2026-05-21T01:00:00+00:00",
            "size_usd": 10.0,
        }
    }))

    summary = mig.migrate(data_dir=data_dir, db_path=tmp_db, dry_run=True)
    assert summary["inserted_rows"] == 0
    assert state_file.exists()
    assert positions.list_positions(db_path=tmp_db) == []


def test_migrate_skips_invalid_rows(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    state_file = data_dir / "altcoin_reversion_state.json"
    state_file.write_text(json.dumps({
        "GOOD/USDT": {
            "entry_price": 100.0,
            "entry_ts": "2026-05-21T01:00:00+00:00",
            "size_usd": 10.0,
        },
        "BAD_PRICE/USDT": {
            "entry_price": 0,
            "entry_ts": "2026-05-21T01:00:00+00:00",
            "size_usd": 10.0,
        },
        "MISSING_TS/USDT": {
            "entry_price": 100.0,
            "size_usd": 10.0,
        },
    }))

    summary = mig.migrate(data_dir=data_dir, db_path=tmp_db,
                          rename_suffix=".migrated_TEST")
    assert summary["inserted_rows"] == 1
    assert len(summary["skipped_invalid"]) == 2
