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


def test_market_peak_survives_engine_reconstruction(isolated_state_file: Path) -> None:
    """
    Per-market peaks must persist across engine reconstructions or the
    per-market kill switch silently resets on every container restart —
    the exact bug behind the phantom-drawdown HALT firings before
    2026-05-18.
    """
    engine = RiskEngine(initial_portfolio=110.0)
    engine.update_market("crypto", 120.0)
    engine.update_market("crypto", 108.0)  # -10% from $120
    assert engine.market_drawdown("crypto") == pytest.approx(-0.10)

    del engine

    fresh_engine = RiskEngine(initial_portfolio=110.0)
    # Reconstructed engine has not seen any market updates yet, but the
    # loaded peak must be visible for seeding on the next update_market call.
    assert fresh_engine._loaded_market_peaks.get("crypto") == pytest.approx(120.0)

    fresh_engine.update_market("crypto", 108.0)
    assert fresh_engine.market_drawdown("crypto") == pytest.approx(-0.10)


def test_market_peaks_isolated_per_market(isolated_state_file: Path) -> None:
    """Crypto and india peaks persist independently."""
    engine = RiskEngine(initial_portfolio=25_120.0)
    engine.update_market("crypto", 120.0)
    engine.update_market("india", 25_000.0)
    engine.update_market("crypto", 100.0)  # -16.7% drawdown — would HALT
    engine.update_market("india", 24_500.0)  # -2% — fine

    del engine

    fresh = RiskEngine(initial_portfolio=25_120.0)
    assert fresh._loaded_market_peaks["crypto"] == pytest.approx(120.0)
    assert fresh._loaded_market_peaks["india"] == pytest.approx(25_000.0)


def test_market_peaks_backward_compatible_with_old_schema(
    isolated_state_file: Path,
) -> None:
    """An old state file lacking ``market_peaks`` must load cleanly."""
    isolated_state_file.write_text(
        '{"peak": 110.0, "last_update_ts": 1.0, "last_equity": 100.0}',
        encoding="utf-8",
    )
    engine = RiskEngine(initial_portfolio=10.0)
    assert engine._portfolio_peak == pytest.approx(110.0)
    assert engine._loaded_market_peaks == {}

    # First update_market call should now seed the per-market peak from
    # current_value (the only signal available) and persist the new schema.
    engine.update_market("crypto", 95.0)
    import json
    data = json.loads(isolated_state_file.read_text(encoding="utf-8"))
    assert data["market_peaks"]["crypto"] == pytest.approx(95.0)


def test_market_peak_seed_uses_max_of_loaded_and_current(
    isolated_state_file: Path,
) -> None:
    """If the persisted peak is higher than current_value, we keep the
    persisted peak — never discard a historical high-water mark."""
    isolated_state_file.write_text(
        '{"peak": 110.0, "last_update_ts": 1.0, "last_equity": 100.0,'
        ' "market_peaks": {"crypto": 120.0}}',
        encoding="utf-8",
    )
    engine = RiskEngine(initial_portfolio=110.0)
    # First post-restart observation is 100 — but the historical peak is 120.
    engine.update_market("crypto", 100.0)
    assert engine.market_drawdown("crypto") == pytest.approx(-1.0 / 6.0, abs=1e-4)
