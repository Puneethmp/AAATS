"""Tests for state/schemas.py (Phase D.3).

Covers:
  - Round-trip per schema with a realistic production-shaped payload.
  - Hard rejection of (a) malformed JSON, (b) wrong-shape JSON, (c) extra
    keys when ConfigDict(extra="forbid") is set.
  - share_equality_mismatches.json round-trip with both empty and populated
    states (the file's wire shape is a bare dict, not nested under a key).
  - validate_all_state_files smoke catches a corrupted production file
    and reports it without raising.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from state.schemas import (
    HaltStateSchema,
    HeartbeatSchema,
    PaperPositionsSchema,
    RiskEngineStateSchema,
    SchemaValidationError,
    ShareEqualityMismatchesSchema,
    load_validated,
    save_validated,
    validate_all_state_files,
)


# ── heartbeat.json ──────────────────────────────────────────────────────────


def test_heartbeat_round_trip_flat(tmp_path: Path) -> None:
    """The flat schema written by live_paper_runner.py:1873 must round-trip."""
    raw = {
        "timestamp": "2026-05-22T03:55:00+00:00",
        "cycle": 95,
        "market": "crypto",
        "cycle_duration_seconds": 12.988,
    }
    p = tmp_path / "heartbeat.json"
    p.write_text(json.dumps(raw))
    model = load_validated(p, HeartbeatSchema)
    assert isinstance(model, HeartbeatSchema)
    assert model.cycle == 95
    assert model.market == "crypto"

    # Re-save and ensure the on-disk form matches.
    out = tmp_path / "heartbeat_out.json"
    save_validated(out, model)
    again = load_validated(out, HeartbeatSchema)
    assert again.timestamp == model.timestamp


def test_heartbeat_rejects_nested_legacy_shape(tmp_path: Path) -> None:
    """The legacy nested-per-market shape from HeartbeatMonitor must fail.

    Catalog row 1: writer/reader drift hid the heartbeat-staleness signal.
    D.3 closes by making the nested shape an explicit validation failure.
    """
    nested = {
        "crypto": {
            "timestamp": "2026-05-22T03:55:00+00:00",
            "market": "crypto",
            "status": "RUNNING",
            "cycle_count": 95,
        }
    }
    p = tmp_path / "heartbeat.json"
    p.write_text(json.dumps(nested))
    with pytest.raises(SchemaValidationError):
        load_validated(p, HeartbeatSchema)


def test_heartbeat_rejects_negative_cycle(tmp_path: Path) -> None:
    bad = {
        "timestamp": "2026-05-22T03:55:00+00:00",
        "cycle": -1,
        "market": "crypto",
        "cycle_duration_seconds": 12.988,
    }
    p = tmp_path / "heartbeat.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(SchemaValidationError):
        load_validated(p, HeartbeatSchema)


# ── halt_state.json ─────────────────────────────────────────────────────────


def test_halt_state_round_trip(tmp_path: Path) -> None:
    raw = {"us": True, "india": True, "crypto": False}  # production state
    p = tmp_path / "halt_state.json"
    p.write_text(json.dumps(raw))
    model = load_validated(p, HaltStateSchema)
    assert model.crypto is False
    assert model.us is True


def test_halt_state_rejects_typo_market(tmp_path: Path) -> None:
    """Extra keys must fail — a `cyrpto` typo would silently inherit
    halt-false otherwise."""
    typo = {"us": False, "india": False, "cyrpto": True}
    p = tmp_path / "halt_state.json"
    p.write_text(json.dumps(typo))
    with pytest.raises(SchemaValidationError):
        load_validated(p, HaltStateSchema)


# ── risk_engine_state.json ──────────────────────────────────────────────────


def test_risk_engine_state_production_shape(tmp_path: Path) -> None:
    """Production payload captured 2026-05-22 from box must validate."""
    raw = {
        "peak": 131.32147002087942,
        "last_update_ts": 1779381583.8155823,
        "last_equity": 101.32746666275996,
        "market_peaks": {"crypto": 131.32147002087942},
    }
    p = tmp_path / "risk_engine_state.json"
    p.write_text(json.dumps(raw))
    model = load_validated(p, RiskEngineStateSchema)
    assert model.market_peaks.crypto == pytest.approx(131.32147)


def test_risk_engine_state_rejects_negative_peak(tmp_path: Path) -> None:
    bad = {
        "peak": -1.0,
        "last_update_ts": 1779381583.0,
        "last_equity": 100.0,
        "market_peaks": {"crypto": 100.0},
    }
    p = tmp_path / "risk_engine_state.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(SchemaValidationError):
        load_validated(p, RiskEngineStateSchema)


# ── paper_positions.json ────────────────────────────────────────────────────


def test_paper_positions_empty(tmp_path: Path) -> None:
    """Production state on box: `{"india": {}, "crypto": {}}` must validate."""
    raw = {"india": {}, "crypto": {}}
    p = tmp_path / "paper_positions.json"
    p.write_text(json.dumps(raw))
    model = load_validated(p, PaperPositionsSchema)
    assert model.india == {} and model.crypto == {}


def test_paper_positions_per_symbol_allowed(tmp_path: Path) -> None:
    """Per-symbol position dicts under each market are allowed (the
    canonical shape may at some point be populated again)."""
    raw = {
        "india": {},
        "crypto": {
            "ETH/USDT": {
                "shares": 0.0005,
                "entry_price": 2106.0,
                "regime": "RANGE_BOUND",
            }
        },
    }
    p = tmp_path / "paper_positions.json"
    p.write_text(json.dumps(raw))
    model = load_validated(p, PaperPositionsSchema)
    assert "ETH/USDT" in model.crypto


def test_paper_positions_rejects_extra_market(tmp_path: Path) -> None:
    """A typo like `cyrpto` must fail (extra=forbid)."""
    bad = {"india": {}, "crypto": {}, "cyrpto": {}}
    p = tmp_path / "paper_positions.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(SchemaValidationError):
        load_validated(p, PaperPositionsSchema)


# ── share_equality_mismatches.json ──────────────────────────────────────────


def test_share_equality_empty_round_trip(tmp_path: Path) -> None:
    """The empty `{}` shape currently on box must round-trip."""
    p = tmp_path / "share_equality_mismatches.json"
    p.write_text("{}")
    model = load_validated(p, ShareEqualityMismatchesSchema)
    assert model.mismatches == {}

    out = tmp_path / "out.json"
    save_validated(out, model)
    assert out.read_text(encoding="utf-8").strip() == "{}"


def test_share_equality_populated_round_trip(tmp_path: Path) -> None:
    """The session-1 finding shape `{"C3_altcoin_reversion|TON/USDT": 6}` round-trips.

    Even if production currently shows `{}`, the schema MUST support
    populated maps so the writer doesn't crash the runner on the next
    mismatch (catalog row 1.b — addendum reliability check).
    """
    raw = {
        "C3_altcoin_reversion|TON/USDT": 6,
        "C3_altcoin_reversion|FET/USDT": 6,
    }
    p = tmp_path / "share_equality_mismatches.json"
    p.write_text(json.dumps(raw))
    model = load_validated(p, ShareEqualityMismatchesSchema)
    assert model.mismatches["C3_altcoin_reversion|TON/USDT"] == 6

    out = tmp_path / "out.json"
    save_validated(out, model)
    again = json.loads(out.read_text(encoding="utf-8"))
    assert again == raw


def test_share_equality_rejects_missing_pipe(tmp_path: Path) -> None:
    bad = {"C3_no_pipe_just_a_string": 6}
    p = tmp_path / "share_equality_mismatches.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(SchemaValidationError):
        load_validated(p, ShareEqualityMismatchesSchema)


def test_share_equality_rejects_negative_count(tmp_path: Path) -> None:
    bad = {"C3_altcoin_reversion|TON/USDT": -1}
    p = tmp_path / "share_equality_mismatches.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(SchemaValidationError):
        load_validated(p, ShareEqualityMismatchesSchema)


# ── Cross-cutting ───────────────────────────────────────────────────────────


def test_load_raises_on_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "halt_state.json"
    p.write_text("{not json")
    with pytest.raises(SchemaValidationError):
        load_validated(p, HaltStateSchema)


def test_validate_all_state_files_reports_missing_and_invalid(tmp_path: Path) -> None:
    # Two of the five files present: one valid, one invalid
    (tmp_path / "halt_state.json").write_text(
        json.dumps({"us": False, "india": False, "crypto": False})
    )
    (tmp_path / "heartbeat.json").write_text("{not json")
    results = validate_all_state_files(tmp_path)
    assert results["halt_state.json"] == "OK"
    assert results["heartbeat.json"].startswith("INVALID:")
    # Required missing → "MISSING"
    assert results["paper_positions.json"] == "MISSING"
    # Optional missing (risk_engine_state lives under state/) → "MISSING_OPTIONAL"
    assert "state\\risk_engine_state.json" in results or \
           "state/risk_engine_state.json" in results
