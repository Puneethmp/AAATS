"""Tests for risk-engine state-file isolation across SYSTEM__TRADING_MODE.

Phase A.1, 2026-05-23. Spec:
docs/decisions/2026-05-22_state_isolation_design.md.

The discriminator precedence under test:
    1. AAATS_RISK_STATE_FILE (explicit) wins.
    2. SYSTEM__TRADING_MODE + AAATS_RISK_STATE_DIR -> per-mode path.
    3. Legacy default (no mode suffix) for back-compat with scripts/tests.

A mode-flip MUST NOT inherit the other mode's peak/drawdown state. Test
case 3 (test_paper_peak_survives_live_session) is the load-bearing
invariant.
"""

from __future__ import annotations

import importlib

import pytest


def _reload_engine_with_env(monkeypatch, **env: str | None):
    """Reload risk.engine after stamping the given env vars.

    ``_state_file_path`` reads env at import time -> tests must reload.
    Returns the reloaded module so the caller can inspect STATE_FILE.
    """
    for key in ("AAATS_RISK_STATE_FILE", "AAATS_RISK_STATE_DIR", "SYSTEM__TRADING_MODE"):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        if v is not None:
            monkeypatch.setenv(k, v)

    import risk.engine as engine
    return importlib.reload(engine)


class TestStateFilePathDiscriminator:
    def test_paper_mode_writes_paper_state(self, monkeypatch, tmp_path):
        engine = _reload_engine_with_env(
            monkeypatch,
            SYSTEM__TRADING_MODE="paper",
            AAATS_RISK_STATE_DIR=str(tmp_path),
        )
        assert engine.STATE_FILE == tmp_path / "risk_engine_state.paper.json"
        # Direct helper call also matches.
        assert engine._state_file_path() == tmp_path / "risk_engine_state.paper.json"

    def test_live_mode_writes_live_state(self, monkeypatch, tmp_path):
        engine = _reload_engine_with_env(
            monkeypatch,
            SYSTEM__TRADING_MODE="live",
            AAATS_RISK_STATE_DIR=str(tmp_path),
        )
        assert engine.STATE_FILE == tmp_path / "risk_engine_state.live.json"

    def test_paper_peak_survives_live_session(self, monkeypatch, tmp_path):
        """Load-bearing invariant: mode-flip preserves both peaks independently.

        Sequence: write a paper peak -> flip to live -> write a live peak ->
        flip back to paper -> paper peak unchanged (NOT overwritten by live).
        """
        # 1. Paper session: write peak via the engine's normal persist path.
        engine = _reload_engine_with_env(
            monkeypatch,
            SYSTEM__TRADING_MODE="paper",
            AAATS_RISK_STATE_DIR=str(tmp_path),
        )
        paper_engine = engine.RiskEngine(initial_portfolio=125.0)
        paper_engine.update_portfolio(150.0)  # peak=150 in paper
        paper_file = tmp_path / "risk_engine_state.paper.json"
        assert paper_file.exists(), "paper write went somewhere else"

        # 2. Flip to live: a fresh engine with no prior live state.
        engine = _reload_engine_with_env(
            monkeypatch,
            SYSTEM__TRADING_MODE="live",
            AAATS_RISK_STATE_DIR=str(tmp_path),
        )
        live_engine = engine.RiskEngine(initial_portfolio=25.0)
        live_engine.update_portfolio(30.0)  # peak=30 in live
        live_file = tmp_path / "risk_engine_state.live.json"
        assert live_file.exists(), "live write went somewhere else"
        # Confirm the two files diverged.
        assert paper_file.read_text(encoding="utf-8") \
            != live_file.read_text(encoding="utf-8")

        # 3. Flip BACK to paper: must reload the paper peak, NOT the live peak.
        engine = _reload_engine_with_env(
            monkeypatch,
            SYSTEM__TRADING_MODE="paper",
            AAATS_RISK_STATE_DIR=str(tmp_path),
        )
        replay = engine.RiskEngine(initial_portfolio=125.0)
        # Internal field rather than the public surface to assert the loaded peak.
        assert replay._portfolio_peak == 150.0, \
            "paper peak was clobbered by the live session"

    def test_legacy_default_when_no_mode_env(self, monkeypatch, tmp_path):
        engine = _reload_engine_with_env(
            monkeypatch,
            AAATS_RISK_STATE_DIR=str(tmp_path),
            # SYSTEM__TRADING_MODE deliberately unset.
        )
        # No mode suffix -> the legacy filename used by pre-A.1 deployments
        # and by ad-hoc scripts that never set SYSTEM__TRADING_MODE.
        assert engine.STATE_FILE == tmp_path / "risk_engine_state.json"

    def test_explicit_override_wins(self, monkeypatch, tmp_path):
        target = tmp_path / "custom_state.json"
        engine = _reload_engine_with_env(
            monkeypatch,
            AAATS_RISK_STATE_FILE=str(target),
            # Even with mode + dir set, the explicit override wins.
            SYSTEM__TRADING_MODE="paper",
            AAATS_RISK_STATE_DIR=str(tmp_path / "ignored"),
        )
        assert engine.STATE_FILE == target

    def test_unknown_mode_falls_back_to_legacy(self, monkeypatch, tmp_path):
        """Anything other than ``paper``/``live`` is treated as no mode set.

        Defense against typos like ``Paper`` or ``LIVE-shadow`` silently
        writing into a non-existent third path; legacy fallback is safer
        than a per-mode path nobody else knows about.
        """
        engine = _reload_engine_with_env(
            monkeypatch,
            SYSTEM__TRADING_MODE="DRY_RUN",
            AAATS_RISK_STATE_DIR=str(tmp_path),
        )
        assert engine.STATE_FILE == tmp_path / "risk_engine_state.json"
