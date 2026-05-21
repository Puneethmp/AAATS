"""Regression + forward tests for C1/C2/C3/C6 unified-ledger wiring (B3).

For each strategy module:
  - Asserts STRATEGY_ID, MARKET, _USE_UNIFIED_LEDGER attributes exist.
  - With flag OFF (default), _load_state / _save_state route through the
    legacy JSON path.
  - With flag ON (monkey-patched), _load_state / _save_state route through
    the foundation.positions table.

C5b funding_arb is NOT covered here -- it is intentionally not wired
(hard constraint, NEXT_PROMPT.md 2026-05-21).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from foundation import positions

# Strategy module name -> (state_file_attr, expected_strategy_id)
STRATEGIES = [
    ("trading.altcoin_reversion", "STATE_FILE",  "C3_altcoin_reversion"),
    ("trading.bollinger_range",   "STATE_FILE",  "C6_bollinger_range"),
    ("trading.stat_arb",          "_STATE_FILE", "C1_stat_arb"),
    ("trading.momentum_breakout", "STATE_FILE",  "C2_momentum"),
]


@pytest.fixture
def tmp_db_path(tmp_path, monkeypatch):
    """Point positions._DEFAULT_DB_PATH at an isolated tmp DB.

    The strategy modules call _state_bridge.save_state without an explicit
    db_path, so the bridge falls through to positions._DEFAULT_DB_PATH.
    Monkey-patching it here keeps each test hermetic.
    """
    db_path = str(tmp_path / "paper_trades.db")
    monkeypatch.setattr(positions, "_DEFAULT_DB_PATH", db_path)
    return db_path


def _strategy_module(mod_name):
    import importlib
    return importlib.import_module(mod_name)


@pytest.mark.parametrize("mod_name,state_attr,strategy_id", STRATEGIES)
def test_strategy_has_ledger_wiring_constants(mod_name, state_attr, strategy_id):
    mod = _strategy_module(mod_name)
    assert hasattr(mod, "STRATEGY_ID")
    assert mod.STRATEGY_ID == strategy_id
    assert getattr(mod, "MARKET") == "crypto"
    assert hasattr(mod, "_USE_UNIFIED_LEDGER")
    assert hasattr(mod, "_load_state")
    assert hasattr(mod, "_save_state")
    assert hasattr(mod, state_attr)


@pytest.mark.parametrize("mod_name,state_attr,strategy_id", STRATEGIES)
def test_strategy_off_branch_round_trip(
    mod_name, state_attr, strategy_id, tmp_path, monkeypatch,
):
    """Flag OFF (default): _save_state writes JSON, _load_state reads it."""
    mod = _strategy_module(mod_name)
    state_file = tmp_path / f"{strategy_id}_state.json"

    monkeypatch.setattr(mod, "_USE_UNIFIED_LEDGER", False)
    monkeypatch.setattr(mod, state_attr, state_file)

    payload = {"SOL/USDT": {
        "entry_price": 100.0,
        "size_usd": 12.0,
        "entry_ts": "2026-05-21T00:00:00+00:00",
    }}
    mod._save_state(payload)
    assert state_file.exists()

    on_disk = json.loads(state_file.read_text())
    assert on_disk == payload

    reloaded = mod._load_state()
    assert reloaded == payload


@pytest.mark.parametrize("mod_name,state_attr,strategy_id", STRATEGIES)
def test_strategy_on_branch_writes_positions_table(
    mod_name, state_attr, strategy_id, tmp_path, tmp_db_path, monkeypatch,
):
    """Flag ON: _save_state writes positions, NOT the JSON file."""
    mod = _strategy_module(mod_name)
    state_file = tmp_path / f"{strategy_id}_state.json"

    monkeypatch.setattr(mod, "_USE_UNIFIED_LEDGER", True)
    monkeypatch.setattr(mod, state_attr, state_file)

    payload = {"SOL/USDT": {
        "entry_price": 100.0,
        "size_usd": 12.0,
        "entry_ts": "2026-05-21T00:00:00+00:00",
        "tag_for_strategy": strategy_id,
    }}
    mod._save_state(payload)
    # ON branch must NOT write the legacy JSON file.
    assert not state_file.exists()

    rows = positions.list_positions(strategy=strategy_id, db_path=tmp_db_path)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SOL/USDT"
    assert rows[0]["entry_price"] == pytest.approx(100.0)
    assert rows[0]["metadata"]["tag_for_strategy"] == strategy_id

    reloaded = mod._load_state()
    assert "SOL/USDT" in reloaded
    assert reloaded["SOL/USDT"]["tag_for_strategy"] == strategy_id


@pytest.mark.parametrize("mod_name,state_attr,strategy_id", STRATEGIES)
def test_strategy_on_branch_close_drops_position(
    mod_name, state_attr, strategy_id, tmp_path, tmp_db_path, monkeypatch,
):
    """Flag ON: removing a symbol from in-memory state closes the DB row."""
    mod = _strategy_module(mod_name)
    state_file = tmp_path / f"{strategy_id}_state.json"

    monkeypatch.setattr(mod, "_USE_UNIFIED_LEDGER", True)
    monkeypatch.setattr(mod, state_attr, state_file)

    mod._save_state({"SOL/USDT": {
        "entry_price": 100.0, "size_usd": 12.0,
        "entry_ts": "2026-05-21T00:00:00+00:00",
    }})
    assert len(positions.list_positions(
        strategy=strategy_id, db_path=tmp_db_path,
    )) == 1

    mod._save_state({})
    assert positions.list_positions(
        strategy=strategy_id, db_path=tmp_db_path,
    ) == []
