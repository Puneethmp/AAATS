"""Unit tests for foundation.positions  —  B1 of unified positions ledger.

Tests required by NEXT_PROMPT.md B1:
  - Round-trip: open -> get -> close -> get returns None
  - Metadata opaque preservation (write arbitrary dict, read back unchanged)
  - Composite-key collision (two strategies, same symbol, both rows coexist)
  - list_positions filters (by strategy, by market, by both, by neither)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from foundation import positions


@pytest.fixture
def db_path(tmp_path):
    """Fresh sqlite DB per test; positions table created lazily."""
    return str(tmp_path / "paper_trades.db")


def _open(db_path: str, **overrides) -> None:
    defaults = dict(
        strategy="C3_altcoin_reversion",
        symbol="SOL/USDT",
        market="crypto",
        entry_shares=0.1234,
        entry_price=100.0,
        size_usd=12.34,
        entry_ts="2026-05-21T00:00:00+00:00",
        correlation_id=None,
        metadata=None,
        db_path=db_path,
    )
    defaults.update(overrides)
    positions.open_position(**defaults)


# --------------------------------------------------------------------------- #
#  Round-trip
# --------------------------------------------------------------------------- #

def test_open_get_close_round_trip(db_path):
    _open(
        db_path,
        symbol="SOL/USDT",
        entry_shares=0.123,
        entry_price=200.0,
        size_usd=24.6,
        entry_ts="2026-05-21T01:23:45+00:00",
        correlation_id="cid-abc",
        metadata={"entry_z": -1.8, "max_z": -1.8},
    )

    fetched = positions.get_position(
        "C3_altcoin_reversion", "SOL/USDT", db_path=db_path
    )
    assert fetched is not None
    assert fetched["strategy"] == "C3_altcoin_reversion"
    assert fetched["symbol"] == "SOL/USDT"
    assert fetched["market"] == "crypto"
    assert fetched["entry_shares"] == pytest.approx(0.123)
    assert fetched["entry_price"] == pytest.approx(200.0)
    assert fetched["size_usd"] == pytest.approx(24.6)
    assert fetched["entry_ts"] == "2026-05-21T01:23:45+00:00"
    assert fetched["entry_correlation_id"] == "cid-abc"
    assert fetched["metadata"] == {"entry_z": -1.8, "max_z": -1.8}

    closed = positions.close_position(
        "C3_altcoin_reversion", "SOL/USDT", db_path=db_path
    )
    assert closed == fetched

    assert (
        positions.get_position(
            "C3_altcoin_reversion", "SOL/USDT", db_path=db_path
        )
        is None
    )


def test_close_position_missing_returns_none(db_path):
    assert (
        positions.close_position(
            "C3_altcoin_reversion", "MISSING/USDT", db_path=db_path
        )
        is None
    )


# --------------------------------------------------------------------------- #
#  Metadata opaque preservation
# --------------------------------------------------------------------------- #

def test_metadata_is_opaque_preserved(db_path):
    blob = {
        "entry_z": -1.85,
        "max_z": -0.42,
        "symbol_vol": 0.057,
        "nested": {"k": [1, 2, 3], "flag": True, "null_field": None},
        "list_of_strs": ["a", "b", "c"],
        "unicode": "alpha-beta-gamma",
    }
    _open(db_path, symbol="LINK/USDT", metadata=blob)
    row = positions.get_position(
        "C3_altcoin_reversion", "LINK/USDT", db_path=db_path
    )
    assert row is not None
    assert row["metadata"] == blob


def test_metadata_none_round_trips(db_path):
    _open(db_path, symbol="AVAX/USDT", metadata=None)
    row = positions.get_position(
        "C3_altcoin_reversion", "AVAX/USDT", db_path=db_path
    )
    assert row is not None
    assert row["metadata"] is None


# --------------------------------------------------------------------------- #
#  Composite-key collision
# --------------------------------------------------------------------------- #

def test_composite_key_two_strategies_same_symbol(db_path):
    _open(
        db_path,
        strategy="C3_altcoin_reversion",
        symbol="SOL/USDT",
        size_usd=10.0,
        metadata={"who": "C3"},
    )
    _open(
        db_path,
        strategy="C6_momentum_breakout",
        symbol="SOL/USDT",
        size_usd=20.0,
        metadata={"who": "C6"},
    )

    c3 = positions.get_position(
        "C3_altcoin_reversion", "SOL/USDT", db_path=db_path
    )
    c6 = positions.get_position(
        "C6_momentum_breakout", "SOL/USDT", db_path=db_path
    )
    assert c3 is not None and c6 is not None
    assert c3["metadata"]["who"] == "C3"
    assert c6["metadata"]["who"] == "C6"
    assert c3["size_usd"] == pytest.approx(10.0)
    assert c6["size_usd"] == pytest.approx(20.0)

    assert len(positions.list_positions(db_path=db_path)) == 2

    positions.close_position(
        "C3_altcoin_reversion", "SOL/USDT", db_path=db_path
    )
    remaining = positions.list_positions(db_path=db_path)
    assert len(remaining) == 1
    assert remaining[0]["strategy"] == "C6_momentum_breakout"


def test_same_strategy_same_symbol_collides(db_path):
    import sqlite3

    _open(db_path, strategy="C3_altcoin_reversion", symbol="SOL/USDT")
    with pytest.raises(sqlite3.IntegrityError):
        _open(db_path, strategy="C3_altcoin_reversion", symbol="SOL/USDT")


# --------------------------------------------------------------------------- #
#  list_positions filters
# --------------------------------------------------------------------------- #

def _seed(db_path: str) -> None:
    _open(db_path, strategy="C3_altcoin_reversion", symbol="SOL/USDT",
          market="crypto")
    _open(db_path, strategy="C3_altcoin_reversion", symbol="LINK/USDT",
          market="crypto")
    _open(db_path, strategy="C6_momentum_breakout", symbol="BTC/USDT",
          market="crypto")
    _open(db_path, strategy="C1_stat_arb", symbol="RELIANCE",
          market="india")


def test_list_positions_no_filter(db_path):
    _seed(db_path)
    rows = positions.list_positions(db_path=db_path)
    assert len(rows) == 4


def test_list_positions_by_strategy(db_path):
    _seed(db_path)
    rows = positions.list_positions(
        strategy="C3_altcoin_reversion", db_path=db_path
    )
    assert len(rows) == 2
    assert {r["symbol"] for r in rows} == {"SOL/USDT", "LINK/USDT"}


def test_list_positions_by_market(db_path):
    _seed(db_path)
    rows = positions.list_positions(market="crypto", db_path=db_path)
    assert len(rows) == 3
    assert all(r["market"] == "crypto" for r in rows)

    india = positions.list_positions(market="india", db_path=db_path)
    assert len(india) == 1
    assert india[0]["symbol"] == "RELIANCE"


def test_list_positions_by_strategy_and_market(db_path):
    _seed(db_path)
    rows = positions.list_positions(
        strategy="C3_altcoin_reversion", market="crypto", db_path=db_path
    )
    assert len(rows) == 2
    rows = positions.list_positions(
        strategy="C3_altcoin_reversion", market="india", db_path=db_path
    )
    assert rows == []


def test_list_positions_ordering_deterministic(db_path):
    _seed(db_path)
    rows = positions.list_positions(db_path=db_path)
    pairs = [(r["strategy"], r["symbol"]) for r in rows]
    assert pairs == sorted(pairs)


# --------------------------------------------------------------------------- #
#  Pydantic boundary validation
# --------------------------------------------------------------------------- #

def test_open_rejects_negative_shares(db_path):
    with pytest.raises(ValidationError):
        _open(db_path, entry_shares=-0.5)


def test_open_rejects_zero_price(db_path):
    with pytest.raises(ValidationError):
        _open(db_path, entry_price=0)


def test_open_rejects_empty_symbol(db_path):
    with pytest.raises(ValidationError):
        _open(db_path, symbol="")


def test_open_rejects_unknown_metadata_via_extra_forbid(db_path):
    # Confirm `extra="forbid"` keeps the input dict strict.
    from foundation.positions import _PositionInput

    with pytest.raises(ValidationError):
        _PositionInput(
            strategy="C3_altcoin_reversion",
            symbol="SOL/USDT",
            market="crypto",
            entry_shares=0.1,
            entry_price=100.0,
            size_usd=10.0,
            entry_ts="2026-05-21T00:00:00+00:00",
            bogus_field="should_be_rejected",
        )
