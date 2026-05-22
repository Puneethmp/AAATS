"""Tests for trading/strategy_isolation.py + risk/strategy_halt.py (Phase D.1).

Three required cases per the session-2 prompt:
  - A strategy that raises on cycle 3 — assert other strategies run on
    that cycle and after (i.e. the helper returns None, the cycle
    continues; sibling strategies don't see the exception).
  - Auto-HALT triggers on cycle 5 (3rd consecutive exception in the
    same strategy).
  - Telegram alert fires on auto-HALT (mocked).

Plus baseline coverage of the helper's state-file persistence.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import risk.strategy_halt as strategy_halt
import trading.strategy_isolation as isolation


@pytest.fixture(autouse=True)
def _isolated_state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point both state files at tmp_path so tests cannot pollute each other
    or the real data/ dir."""
    monkeypatch.setattr(isolation, "STATE_FILE",
                        tmp_path / "strategy_exception_state.json")
    monkeypatch.setattr(strategy_halt, "STRATEGY_HALT_FILE",
                        tmp_path / "strategy_halt_state.json")
    return tmp_path


def test_success_clears_streak(_isolated_state_files: Path) -> None:
    def good() -> str:
        return "ok"
    assert isolation.run_strategy_with_isolation("C2_momentum", good) == "ok"
    # The state file may not exist yet — no exceptions recorded.
    if isolation.STATE_FILE.exists():
        state = json.loads(isolation.STATE_FILE.read_text(encoding="utf-8"))
        assert state.get("C2_momentum", {}).get("consecutive_exceptions", 0) == 0


def test_single_exception_does_not_halt(_isolated_state_files: Path) -> None:
    def boom() -> None:
        raise RuntimeError("boom")
    result = isolation.run_strategy_with_isolation("C1_stat_arb", boom)
    assert result is None
    assert not strategy_halt.is_strategy_halted("C1_stat_arb")
    state = json.loads(isolation.STATE_FILE.read_text(encoding="utf-8"))
    assert state["C1_stat_arb"]["consecutive_exceptions"] == 1
    assert state["C1_stat_arb"]["total_exceptions"] == 1


def test_three_consecutive_exceptions_auto_halt(
    _isolated_state_files: Path,
) -> None:
    """3rd consecutive raise → strategy halted, sibling strategies still
    callable in the same cycle."""
    raise_count = [0]

    def flaky() -> None:
        raise_count[0] += 1
        raise ValueError(f"raise #{raise_count[0]}")

    def sibling_ok() -> str:
        return "sibling-ran"

    # Cycle 1: C3 raises, C6 sibling still runs.
    assert isolation.run_strategy_with_isolation("C3_altcoin_reversion", flaky) is None
    assert isolation.run_strategy_with_isolation("C6_bollinger_range", sibling_ok) == "sibling-ran"
    assert not strategy_halt.is_strategy_halted("C3_altcoin_reversion")

    # Cycle 2: C3 raises again, still not halted.
    isolation.run_strategy_with_isolation("C3_altcoin_reversion", flaky)
    assert not strategy_halt.is_strategy_halted("C3_altcoin_reversion")

    # Cycle 3: 3rd raise → auto-halt fires.
    isolation.run_strategy_with_isolation("C3_altcoin_reversion", flaky)
    assert strategy_halt.is_strategy_halted("C3_altcoin_reversion")

    # Sibling still runnable in the same cycle (halt is per-strategy).
    assert isolation.run_strategy_with_isolation("C6_bollinger_range", sibling_ok) == "sibling-ran"
    assert not strategy_halt.is_strategy_halted("C6_bollinger_range")


def test_auto_halt_fires_telegram_alert(_isolated_state_files: Path) -> None:
    """observability.alerts.send_alert must be called when auto-halt
    fires (gated by the existing alert sender so production rules apply)."""
    def boom() -> None:
        raise RuntimeError("boom")

    with patch("observability.alerts.send_alert") as mock_alert:
        for _ in range(isolation.CONSECUTIVE_HALT_THRESHOLD):
            isolation.run_strategy_with_isolation("C3_altcoin_reversion", boom)

    assert mock_alert.called
    args, kwargs = mock_alert.call_args
    msg = args[0] if args else kwargs.get("text", "")
    assert "STRATEGY AUTO-HALT" in msg
    assert "C3_altcoin_reversion" in msg


def test_success_after_exceptions_resets_consecutive_count(
    _isolated_state_files: Path,
) -> None:
    """A success after two failures resets the consecutive count to 0 so
    sporadic failures don't pile up over weeks."""
    state_counter = [0]

    def sometimes_ok() -> int:
        state_counter[0] += 1
        if state_counter[0] <= 2:
            raise RuntimeError("transient")
        return state_counter[0]

    # 2 raises, 1 success, 1 raise — should NOT auto-halt
    isolation.run_strategy_with_isolation("C1_stat_arb", sometimes_ok)
    isolation.run_strategy_with_isolation("C1_stat_arb", sometimes_ok)
    isolation.run_strategy_with_isolation("C1_stat_arb", sometimes_ok)  # success, resets
    isolation.run_strategy_with_isolation("C1_stat_arb", sometimes_ok)  # next call also succeeds
    assert not strategy_halt.is_strategy_halted("C1_stat_arb")


def test_already_halted_strategy_skips_dispatch(
    _isolated_state_files: Path,
) -> None:
    """A pre-existing halt makes run_strategy_with_isolation a no-op."""
    strategy_halt.halt_strategy("C5b_funding_arb",
                                reason="halted-by-test",
                                consecutive_exceptions=0)
    called = []

    def should_not_be_called() -> None:
        called.append(True)

    result = isolation.run_strategy_with_isolation(
        "C5b_funding_arb", should_not_be_called,
    )
    assert result is None
    assert called == []


def test_reset_strategy_allows_dispatch_again(
    _isolated_state_files: Path,
) -> None:
    strategy_halt.halt_strategy("C2_momentum", reason="test", consecutive_exceptions=3)
    strategy_halt.reset_strategy("C2_momentum",
                                 authorized_by="test",
                                 reason="cleared in test")
    assert not strategy_halt.is_strategy_halted("C2_momentum")
    # Dispatch now succeeds.
    assert isolation.run_strategy_with_isolation(
        "C2_momentum", lambda: "ok",
    ) == "ok"
