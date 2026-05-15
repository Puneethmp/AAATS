"""
tests/test_risk_engine_persistence.py — drawdown-peak persistence

Verifies the P0 fix for the kill-switch regression where every container
restart re-seeded the risk engine peak from cash and silently masked any
live drawdown. After this fix the peak survives reconstructions of the
RiskEngine within the same STATE_FILE.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import risk.engine as risk_engine_module
from risk.engine import RiskEngine


@pytest.fixture
def isolated_state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point STATE_FILE at a temp file so each test starts from a clean slate."""
    state_file = tmp_path / "risk_engine_state.json"
    monkeypatch.setattr(risk_engine_module, "STATE_FILE", state_file)
    return state_file


def test_drawdown_from_locked_peak(isolated_state_file: Path) -> None:
    """Peak seeded at $110 → equity $95 → drawdown ≈ -13.6%."""
    engine = RiskEngine(initial_portfolio=110.0)

    decision = engine.update_portfolio(95.0)

    assert decision.action == "ALLOW"
    assert engine.portfolio_drawdown() == pytest.approx(-0.13636, abs=1e-4)
    assert isolated_state_file.exists(), "state file should be persisted after update"


def test_peak_survives_engine_reconstruction(isolated_state_file: Path) -> None:
    """
    After driving equity to $95, destroying the engine and reconstructing it
    with a tiny initial_portfolio (simulating cash-only seeding on restart)
    must NOT collapse the peak. The peak is loaded from STATE_FILE.
    """
    engine = RiskEngine(initial_portfolio=110.0)
    engine.update_portfolio(95.0)
    assert engine.portfolio_drawdown() == pytest.approx(-0.13636, abs=1e-4)

    del engine

    # Simulate a restart where the runner mistakenly seeded the engine with
    # current cash ($95). The peak loaded from disk must override that.
    fresh_engine = RiskEngine(initial_portfolio=95.0)
    assert fresh_engine._portfolio_peak == pytest.approx(110.0)

    # Drive a fresh update at $95 — drawdown must still be -13.6%, not 0%.
    fresh_engine.update_portfolio(95.0)
    assert fresh_engine.portfolio_drawdown() == pytest.approx(-0.13636, abs=1e-4)


def test_doctrine_fallback_when_no_state_file(isolated_state_file: Path) -> None:
    """
    No STATE_FILE on disk and a tiny initial_portfolio → peak falls back to
    LOCKED_STARTING_EQUITY (110.0), not to the (incorrect) cash seed.
    """
    assert not isolated_state_file.exists()
    engine = RiskEngine(initial_portfolio=10.0)
    assert engine._portfolio_peak == pytest.approx(110.0)
