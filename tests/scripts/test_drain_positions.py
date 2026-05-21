"""Tests for scripts/drain_positions.py and scripts/deploy_ledger_flag.py."""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from foundation import positions
from scripts import drain_positions
from scripts import deploy_ledger_flag


# --------------------------------------------------------------------------- #
#  drain_positions
# --------------------------------------------------------------------------- #

@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "paper_trades.db")
    positions._conn(db_path).close()
    return db_path


def test_drain_clean_writes_history_and_returns_clean(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    history = tmp_path / "ledger_flag_history.json"
    history.write_text(json.dumps({"events": [], "current_value": False}))

    clean, a_off, b_off = drain_positions.drain_check(
        data_dir=data_dir, db_path=tmp_db, history_path=history,
    )
    assert clean is True
    assert a_off == []
    assert b_off == []

    doc = json.loads(history.read_text())
    assert len(doc["events"]) == 1
    assert doc["events"][0]["type"] == "drain_ok"


def test_drain_fails_with_source_a_open(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    history = tmp_path / "ledger_flag_history.json"
    history.write_text(json.dumps({"events": [], "current_value": False}))

    (data_dir / "altcoin_reversion_state.json").write_text(json.dumps({
        "SOL/USDT": {
            "entry_price": 100.0, "size_usd": 10.0,
            "entry_ts": "2026-05-21T00:00:00+00:00",
        }
    }))

    clean, a_off, b_off = drain_positions.drain_check(
        data_dir=data_dir, db_path=tmp_db, history_path=history,
    )
    assert clean is False
    assert a_off == ["altcoin_reversion_state.json:SOL/USDT"]
    assert b_off == []
    # History must NOT have been written on failure.
    doc = json.loads(history.read_text())
    assert doc["events"] == []


def test_drain_fails_with_source_b_open(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    history = tmp_path / "ledger_flag_history.json"
    history.write_text(json.dumps({"events": [], "current_value": False}))

    positions.open_position(
        strategy="C3_altcoin_reversion", symbol="SOL/USDT", market="crypto",
        entry_shares=0.1, entry_price=100.0, size_usd=10.0,
        entry_ts="2026-05-21T00:00:00+00:00", db_path=tmp_db,
    )

    clean, a_off, b_off = drain_positions.drain_check(
        data_dir=data_dir, db_path=tmp_db, history_path=history,
    )
    assert clean is False
    assert a_off == []
    assert b_off == ["C3_altcoin_reversion:SOL/USDT"]


def test_drain_ignores_cooldown_and_halt(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    history = tmp_path / "ledger_flag_history.json"
    history.write_text(json.dumps({"events": [], "current_value": False}))

    (data_dir / "altcoin_reversion_cooldown.json").write_text(
        json.dumps({"SOL/USDT": "2026-05-22T00:00:00+00:00"})
    )
    (data_dir / "halt_state.json").write_text("{}")

    clean, _a, _b = drain_positions.drain_check(
        data_dir=data_dir, db_path=tmp_db, history_path=history,
    )
    assert clean is True


def test_drain_skips_empty_state_files(tmp_db, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    history = tmp_path / "ledger_flag_history.json"
    history.write_text(json.dumps({"events": [], "current_value": False}))

    (data_dir / "stat_arb_state.json").write_text("{}")
    (data_dir / "altcoin_reversion_state.json").write_text("{}")

    clean, a_off, _ = drain_positions.drain_check(
        data_dir=data_dir, db_path=tmp_db, history_path=history,
    )
    assert clean is True
    assert a_off == []


# --------------------------------------------------------------------------- #
#  deploy_ledger_flag helpers (no SSH)
# --------------------------------------------------------------------------- #

def test_find_recent_drain_ok_returns_none_when_stale(tmp_path):
    history = tmp_path / "h.json"
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    history.write_text(json.dumps({
        "events": [{"type": "drain_ok", "timestamp": old_ts}],
        "current_value": False,
    }))
    assert deploy_ledger_flag.find_recent_drain_ok(history) is None


def test_find_recent_drain_ok_returns_event_when_fresh(tmp_path):
    history = tmp_path / "h.json"
    fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    history.write_text(json.dumps({
        "events": [{"type": "drain_ok", "timestamp": fresh_ts}],
        "current_value": False,
    }))
    event = deploy_ledger_flag.find_recent_drain_ok(history)
    assert event is not None
    assert event["timestamp"] == fresh_ts


def test_render_env_replaces_existing_line():
    body = deploy_ledger_flag.render_env(
        "PAPER_MODE=True\nUSE_UNIFIED_LEDGER=False\nFOO=bar\n", True,
    )
    assert "USE_UNIFIED_LEDGER=True" in body
    assert body.count("USE_UNIFIED_LEDGER") == 1
    assert "PAPER_MODE=True" in body
    assert "FOO=bar" in body


def test_render_env_appends_when_missing():
    body = deploy_ledger_flag.render_env("PAPER_MODE=True\n", True)
    assert "USE_UNIFIED_LEDGER=True" in body
    assert "PAPER_MODE=True" in body


def test_parse_bool_accepts_common_forms():
    assert deploy_ledger_flag.parse_bool("true") is True
    assert deploy_ledger_flag.parse_bool("FALSE") is False
    assert deploy_ledger_flag.parse_bool("yes") is True
    assert deploy_ledger_flag.parse_bool("0") is False
    with pytest.raises(ValueError):
        deploy_ledger_flag.parse_bool("maybe")


def test_append_history_creates_file_if_absent(tmp_path):
    history = tmp_path / "new.json"
    deploy_ledger_flag.append_history(
        history,
        {
            "type": "flag_flipped",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "new_value": True,
        },
    )
    doc = json.loads(history.read_text())
    assert doc["current_value"] is True
    assert doc["events"][-1]["type"] == "flag_flipped"


def test_main_aborts_without_recent_drain(tmp_path, capsys):
    history = tmp_path / "h.json"
    history.write_text(json.dumps({"events": [], "current_value": False}))
    rc = deploy_ledger_flag.main([
        "--set", "true",
        "--history-path", str(history),
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no drain_ok event" in err
