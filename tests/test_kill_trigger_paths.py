"""
Kill-trigger path coverage (post-2026-05-23 investigation).

Covers the two regression-prone surfaces identified in
docs/known_issues/2026-05-23_kill_trigger_investigation.md:

  1. The risk engine's HALT_MARKET fires when a single update_market call
     observes drawdown <= -15% (verdict (d) confirmation).
  2. run_crypto short-circuits when foundation/kill_switch.is_halted("crypto")
     returns True (parity with run_india, addressing the asymmetric gap).

Both are pure-behavior tests; no Binance, no DB, no Docker required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from risk.engine import MARKET_DRAWDOWN_HALT, RiskEngine


# ── (1) Engine: HALT_MARKET fires at -16% drawdown ──────────────────────────


def test_engine_halts_market_at_negative_16_pct(tmp_path: Path, monkeypatch) -> None:
    """Drop equity from a $131.32 peak to $87.45 (-33.4%) and confirm
    update_market returns HALT_MARKET with allowed_fraction=0.0."""
    state_file = tmp_path / "risk_engine_state.paper.json"
    state_file.write_text(
        json.dumps({
            "peak": 131.32, "last_equity": 87.45,
            "last_update_ts": 1779513912.0,
            "market_peaks": {"crypto": 131.32},
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AAATS_RISK_STATE_FILE", str(state_file))
    # Re-evaluate STATE_FILE at module level after env change.
    from importlib import reload
    import risk.engine as engine_mod
    reload(engine_mod)

    engine = engine_mod.RiskEngine(initial_portfolio=131.32)
    decision = engine.update_market("crypto", 87.45)

    assert decision.action == "HALT_MARKET", (
        f"expected HALT_MARKET at -33.4% drawdown, got {decision.action} "
        f"({decision.reason})"
    )
    assert decision.allowed_fraction == 0.0
    assert "crypto" in engine._halted_markets


def test_engine_does_not_halt_at_negative_14_pct(tmp_path: Path, monkeypatch) -> None:
    """Symmetric guard: -14% drawdown must NOT trigger HALT_MARKET."""
    state_file = tmp_path / "risk_engine_state.paper.json"
    state_file.write_text(
        json.dumps({
            "peak": 100.0, "last_equity": 86.0,
            "last_update_ts": 1779513912.0,
            "market_peaks": {"crypto": 100.0},
        }),
        encoding="utf-8",
    )
    monkeypatch.setenv("AAATS_RISK_STATE_FILE", str(state_file))
    from importlib import reload
    import risk.engine as engine_mod
    reload(engine_mod)

    engine = engine_mod.RiskEngine(initial_portfolio=100.0)
    decision = engine.update_market("crypto", 86.0)

    assert decision.action == "ALLOW", (
        f"expected ALLOW at -14% drawdown, got {decision.action}"
    )


# ── (2) run_crypto: proceeds past is_halted to MTM and exits ────────────────
#
# Session 8 (2026-05-23) revised semantics: the operator halt is a
# "block new entries" channel, NOT a "freeze the book" channel. run_crypto
# must reach _binance_healthy and _check_trailing_stops even when
# is_halted("crypto") is True, otherwise open positions silently
# accumulate stale pnl that the engine kill was specifically designed to
# keep visible. The per-emission entry gate (apply_kill_switch_gate)
# blocks new BUYs; exits route through apply_kill_switch_exit_gate.
# See: docs/known_issues/2026-05-23_kill_trigger_investigation.md and
# tests/test_operator_halt_mtm_gap.py for the new entry/exit-gate
# coverage.


def test_run_crypto_reaches_binance_probe_even_when_halted() -> None:
    """When is_halted('crypto')=True, run_crypto must still reach the
    Binance health probe so the cycle can MTM open positions and run
    _check_trailing_stops. Pre-session-8 the runner short-circuited
    before _binance_healthy; post-session-8 it proceeds and lets the
    per-emission entry gate block BUYs."""
    from trading import live_paper_runner

    binance_called = {"n": 0}

    def fake_binance_healthy() -> bool:
        binance_called["n"] += 1
        # Return False so the cycle exits before any actual trading;
        # we just need to assert the probe was reached.
        return False

    with (
        patch("foundation.kill_switch.is_halted", return_value=True),
        patch.object(live_paper_runner, "_binance_healthy", side_effect=fake_binance_healthy),
    ):
        live_paper_runner.run_crypto(
            positions={"crypto": {}},
            portfolio={"crypto": {"capital": 100.0}},
        )

    assert binance_called["n"] == 1, (
        "run_crypto short-circuited before _binance_healthy under operator "
        "halt — pre-session-8 bug regression. MTM + exits would never fire."
    )


def test_run_crypto_proceeds_when_not_halted() -> None:
    """Symmetric guard: when the kill switch is clear, run_crypto reaches
    _binance_healthy. We stub the probe to False so the cycle exits before
    any real I/O."""
    from trading import live_paper_runner

    binance_called = {"n": 0}

    def fake_binance_healthy() -> bool:
        binance_called["n"] += 1
        return False  # exit before any actual trading

    with (
        patch("foundation.kill_switch.is_halted", return_value=False),
        patch.object(live_paper_runner, "_binance_healthy", side_effect=fake_binance_healthy),
    ):
        live_paper_runner.run_crypto(
            positions={"crypto": {}},
            portfolio={"crypto": {"capital": 100.0}},
        )

    assert binance_called["n"] == 1, (
        "run_crypto did not reach the Binance health probe when the kill "
        "switch was clear (cycle is broken in the opposite direction)"
    )


# ── (3) Sanity: MARKET_DRAWDOWN_HALT constant unchanged ─────────────────────


def test_market_drawdown_halt_constant_locked() -> None:
    """If anyone ever changes MARKET_DRAWDOWN_HALT, this test catches it.
    The doctrine value is -0.15 (-15%); a change here must come with an
    operator-approved doctrine amendment."""
    assert MARKET_DRAWDOWN_HALT == -0.15
