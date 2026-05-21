"""Tests for foundation.state_bridge and update_position_metadata."""

from __future__ import annotations

import json
import pathlib

import pytest

from foundation import positions, state_bridge


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "paper_trades.db")


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "state.json"


# --------------------------------------------------------------------------- #
#  is_unified_ledger_enabled
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value,expected", [
    ("true", True), ("True", True), ("TRUE", True),
    ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("", False),
    ("nope", False),
])
def test_flag_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("USE_UNIFIED_LEDGER", value)
    assert state_bridge.is_unified_ledger_enabled() is expected


def test_flag_missing_defaults_false(monkeypatch):
    monkeypatch.delenv("USE_UNIFIED_LEDGER", raising=False)
    assert state_bridge.is_unified_ledger_enabled() is False


# --------------------------------------------------------------------------- #
#  OFF branch (legacy JSON)
# --------------------------------------------------------------------------- #

def test_off_branch_load_missing_file(state_file, db_path):
    out = state_bridge.load_state(
        "C3_altcoin_reversion", "crypto", state_file,
        use_unified=False, db_path=db_path,
    )
    assert out == {}


def test_off_branch_save_and_reload(state_file, db_path):
    new_state = {"SOL/USDT": {"entry_price": 100.0, "size_usd": 12.0,
                              "entry_ts": "2026-05-21T00:00:00+00:00",
                              "entry_z": -1.8}}
    state_bridge.save_state(
        "C3_altcoin_reversion", "crypto", new_state, state_file,
        use_unified=False, db_path=db_path,
    )
    assert state_file.exists()
    reloaded = state_bridge.load_state(
        "C3_altcoin_reversion", "crypto", state_file,
        use_unified=False, db_path=db_path,
    )
    assert reloaded == new_state
    # Atomic-rename helper should not leave a .tmp on disk.
    tmps = list(state_file.parent.glob("*.tmp"))
    assert tmps == []


def test_off_branch_corrupt_file_returns_empty(state_file, db_path):
    state_file.write_text("{not valid json")
    out = state_bridge.load_state(
        "C3_altcoin_reversion", "crypto", state_file,
        use_unified=False, db_path=db_path,
    )
    assert out == {}


# --------------------------------------------------------------------------- #
#  ON branch (positions table)
# --------------------------------------------------------------------------- #

def test_on_branch_save_open_close_roundtrip(state_file, db_path):
    # Open one symbol.
    state = {"SOL/USDT": {"entry_price": 100.0, "size_usd": 12.0,
                          "entry_ts": "2026-05-21T00:00:00+00:00",
                          "entry_z": -1.8}}
    state_bridge.save_state(
        "C3_altcoin_reversion", "crypto", state, state_file,
        use_unified=True, db_path=db_path,
    )

    # ON-branch save MUST NOT write the legacy JSON file.
    assert not state_file.exists()

    # ON-branch load returns the same shape.
    loaded = state_bridge.load_state(
        "C3_altcoin_reversion", "crypto", state_file,
        use_unified=True, db_path=db_path,
    )
    assert "SOL/USDT" in loaded
    assert loaded["SOL/USDT"]["entry_price"] == pytest.approx(100.0)
    assert loaded["SOL/USDT"]["size_usd"] == pytest.approx(12.0)
    assert loaded["SOL/USDT"]["entry_ts"] == "2026-05-21T00:00:00+00:00"
    assert loaded["SOL/USDT"]["entry_z"] == pytest.approx(-1.8)

    # Now remove it -- bridge should issue close_position.
    state_bridge.save_state(
        "C3_altcoin_reversion", "crypto", {}, state_file,
        use_unified=True, db_path=db_path,
    )
    assert positions.list_positions(db_path=db_path) == []


def test_on_branch_metadata_update(state_file, db_path):
    # Open with max_z=-1.8
    state = {"SOL/USDT": {"entry_price": 100.0, "size_usd": 12.0,
                          "entry_ts": "2026-05-21T00:00:00+00:00",
                          "entry_z": -1.8, "max_z": -1.8}}
    state_bridge.save_state(
        "C3_altcoin_reversion", "crypto", state, state_file,
        use_unified=True, db_path=db_path,
    )
    # Trailing-exit-style update: max_z rises to -0.4
    state["SOL/USDT"]["max_z"] = -0.4
    state_bridge.save_state(
        "C3_altcoin_reversion", "crypto", state, state_file,
        use_unified=True, db_path=db_path,
    )
    loaded = state_bridge.load_state(
        "C3_altcoin_reversion", "crypto", state_file,
        use_unified=True, db_path=db_path,
    )
    assert loaded["SOL/USDT"]["max_z"] == pytest.approx(-0.4)
    # Original entry_z preserved.
    assert loaded["SOL/USDT"]["entry_z"] == pytest.approx(-1.8)


def test_on_branch_no_position_collision_across_strategies(state_file, db_path):
    s_c3 = {"SOL/USDT": {"entry_price": 100.0, "size_usd": 12.0,
                         "entry_ts": "2026-05-21T00:00:00+00:00",
                         "tag": "C3"}}
    s_c6 = {"SOL/USDT": {"entry_price": 90.0, "size_usd": 6.0,
                         "entry_ts": "2026-05-21T00:00:00+00:00",
                         "tag": "C6"}}
    state_bridge.save_state(
        "C3_altcoin_reversion", "crypto", s_c3, state_file,
        use_unified=True, db_path=db_path,
    )
    state_bridge.save_state(
        "C6_bollinger_range", "crypto", s_c6, state_file,
        use_unified=True, db_path=db_path,
    )
    c3_loaded = state_bridge.load_state(
        "C3_altcoin_reversion", "crypto", state_file,
        use_unified=True, db_path=db_path,
    )
    c6_loaded = state_bridge.load_state(
        "C6_bollinger_range", "crypto", state_file,
        use_unified=True, db_path=db_path,
    )
    assert c3_loaded["SOL/USDT"]["tag"] == "C3"
    assert c6_loaded["SOL/USDT"]["tag"] == "C6"


def test_on_branch_entry_shares_from_explicit_field(state_file, db_path):
    # When state carries entry_shares, the bridge uses that instead of
    # size_usd/entry_price (heals exit-sizing residuals if the strategy
    # is updated to record real fill quantity).
    state = {"SOL/USDT": {"entry_price": 100.0, "size_usd": 12.0,
                          "entry_ts": "2026-05-21T00:00:00+00:00",
                          "entry_shares": 0.118}}
    state_bridge.save_state(
        "C3_altcoin_reversion", "crypto", state, state_file,
        use_unified=True, db_path=db_path,
    )
    row = positions.get_position(
        "C3_altcoin_reversion", "SOL/USDT", db_path=db_path,
    )
    assert row["entry_shares"] == pytest.approx(0.118)


# --------------------------------------------------------------------------- #
#  update_position_metadata
# --------------------------------------------------------------------------- #

def test_update_position_metadata_changes_only_metadata(db_path):
    positions.open_position(
        strategy="C3_altcoin_reversion", symbol="SOL/USDT", market="crypto",
        entry_shares=0.1, entry_price=100.0, size_usd=10.0,
        entry_ts="2026-05-21T00:00:00+00:00",
        metadata={"x": 1}, db_path=db_path,
    )
    ok = positions.update_position_metadata(
        "C3_altcoin_reversion", "SOL/USDT", {"x": 2, "y": "hi"},
        db_path=db_path,
    )
    assert ok is True
    row = positions.get_position(
        "C3_altcoin_reversion", "SOL/USDT", db_path=db_path,
    )
    assert row["metadata"] == {"x": 2, "y": "hi"}
    assert row["entry_price"] == pytest.approx(100.0)
    assert row["entry_shares"] == pytest.approx(0.1)


def test_update_position_metadata_returns_false_when_missing(db_path):
    ok = positions.update_position_metadata(
        "C3_altcoin_reversion", "NOSUCH/USDT", {"x": 1}, db_path=db_path,
    )
    assert ok is False


def test_update_position_metadata_clear_to_none(db_path):
    positions.open_position(
        strategy="C1_stat_arb", symbol="ETH/USDT", market="crypto",
        entry_shares=0.5, entry_price=200.0, size_usd=100.0,
        entry_ts="2026-05-21T00:00:00+00:00",
        metadata={"k": 1}, db_path=db_path,
    )
    positions.update_position_metadata(
        "C1_stat_arb", "ETH/USDT", None, db_path=db_path,
    )
    row = positions.get_position(
        "C1_stat_arb", "ETH/USDT", db_path=db_path,
    )
    assert row["metadata"] is None
