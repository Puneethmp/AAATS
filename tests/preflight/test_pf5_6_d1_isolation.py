"""PF5.6 — D.1 auto-halt isolation stress test.

Pre-soak gating check that the strategy-isolation envelope still
behaves correctly under the conditions the operator-away protocol
relies on:

  * 3 consecutive exceptions on one strategy auto-halts THAT strategy
    (and writes data/strategy_halt_state.json accordingly).
  * Sibling strategies (C1, C6) continue to dispatch in the same cycle
    and on subsequent cycles after the halt fires.
  * The halt scope is strategy-wide (matches the
    risk/strategy_halt.py spec — keyed by strategy_id, not by symbol).
  * reset_strategy() clears the halt and re-enables dispatch.

This is a thicker scenario test than tests/test_strategy_isolation.py
— it walks through the multi-strategy interleave that the soak will
actually exercise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import risk.strategy_halt as strategy_halt
import trading.strategy_isolation as isolation


@pytest.fixture(autouse=True)
def _isolated_state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        isolation, "STATE_FILE", tmp_path / "strategy_exception_state.json"
    )
    monkeypatch.setattr(
        strategy_halt, "STRATEGY_HALT_FILE", tmp_path / "strategy_halt_state.json"
    )
    return tmp_path


def test_c3_three_consec_exceptions_auto_halts_only_c3(
    _isolated_state_files: Path,
) -> None:
    """3 consec C3 raises -> strategy_halt_state.json shows c3=halted,
    C1 and C6 entries are absent or halted=False."""

    def c3_boom() -> None:
        raise RuntimeError("C3 synthetic failure")

    def c1_ok() -> str:
        return "c1-ran"

    def c6_ok() -> str:
        return "c6-ran"

    # 3 cycles: C1 OK, C3 raises, C6 OK each time.
    for _cycle in range(3):
        assert isolation.run_strategy_with_isolation("C1_stat_arb", c1_ok) == "c1-ran"
        isolation.run_strategy_with_isolation("C3_altcoin_reversion", c3_boom)
        assert isolation.run_strategy_with_isolation("C6_bollinger_range", c6_ok) == "c6-ran"

    halt_path = _isolated_state_files / "strategy_halt_state.json"
    assert halt_path.exists(), "halt state file must be written after auto-halt"
    halt_state = json.loads(halt_path.read_text(encoding="utf-8"))
    assert halt_state["C3_altcoin_reversion"]["halted"] is True
    # C1 / C6 must not be flagged halted (entries may be absent or False).
    assert not halt_state.get("C1_stat_arb", {}).get("halted", False)
    assert not halt_state.get("C6_bollinger_range", {}).get("halted", False)


def test_c1_and_c6_continue_dispatching_after_c3_halts(
    _isolated_state_files: Path,
) -> None:
    """After C3 auto-halts, the next 5 cycles must still dispatch C1+C6.
    The runner depends on this for the operator-away soak — a halted
    strategy must NOT cascade into a market-wide stop."""

    def boom() -> None:
        raise RuntimeError("boom")

    # Trip the C3 halt.
    for _ in range(isolation.CONSECUTIVE_HALT_THRESHOLD):
        isolation.run_strategy_with_isolation("C3_altcoin_reversion", boom)
    assert strategy_halt.is_strategy_halted("C3_altcoin_reversion")

    c1_calls = [0]
    c6_calls = [0]

    def c1_ok() -> str:
        c1_calls[0] += 1
        return f"c1-{c1_calls[0]}"

    def c6_ok() -> str:
        c6_calls[0] += 1
        return f"c6-{c6_calls[0]}"

    # 5 post-halt cycles: C1+C6 must still run; C3 must short-circuit.
    for _ in range(5):
        assert isolation.run_strategy_with_isolation("C1_stat_arb", c1_ok) is not None
        assert isolation.run_strategy_with_isolation("C3_altcoin_reversion", boom) is None
        assert isolation.run_strategy_with_isolation("C6_bollinger_range", c6_ok) is not None

    assert c1_calls[0] == 5
    assert c6_calls[0] == 5


def test_halt_scope_is_strategy_id_not_symbol(_isolated_state_files: Path) -> None:
    """A halted strategy is halted across ALL symbols it would otherwise
    trade. The risk/strategy_halt.py spec is keyed by strategy_id, not
    by (strategy_id, symbol)."""
    strategy_halt.halt_strategy(
        "C3_altcoin_reversion",
        reason="test-scope-check",
        consecutive_exceptions=3,
    )

    # Even calls that conceptually target different symbols must be
    # short-circuited — the helper takes only strategy_id.
    calls = []

    def per_symbol(symbol: str) -> str:
        calls.append(symbol)
        return f"ran-{symbol}"

    for symbol in ("SOL/USDT", "LINK/USDT", "AVAX/USDT", "DOT/USDT"):
        result = isolation.run_strategy_with_isolation(
            "C3_altcoin_reversion", per_symbol, symbol,
        )
        assert result is None, (
            f"halt scope leaked: C3 still ran for {symbol}"
        )

    assert calls == [], (
        f"halt should suppress all symbols for the strategy; got {calls}"
    )


def test_reset_strategy_clears_halt_and_re_enables_dispatch(
    _isolated_state_files: Path,
) -> None:
    """reset_strategy("C3") must clear the halt and allow the next
    dispatch to actually run the strategy's function."""
    strategy_halt.halt_strategy(
        "C3_altcoin_reversion",
        reason="pre-test setup",
        consecutive_exceptions=3,
    )
    assert strategy_halt.is_strategy_halted("C3_altcoin_reversion")

    strategy_halt.reset_strategy(
        "C3_altcoin_reversion",
        authorized_by="pf5.6 test",
        reason="test reset behavior",
    )

    assert not strategy_halt.is_strategy_halted("C3_altcoin_reversion")

    ran = []

    def c3_now_ok() -> str:
        ran.append(True)
        return "c3-recovered"

    result = isolation.run_strategy_with_isolation("C3_altcoin_reversion", c3_now_ok)
    assert result == "c3-recovered"
    assert ran == [True]
