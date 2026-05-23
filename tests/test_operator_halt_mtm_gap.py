"""
Session 8 [0] — operator-halt MTM gap resolution.

Asserts that the operator halt channel (data/halt_state.json, set by
kill.py CLI or foundation.kill_switch.halt()) blocks NEW ENTRIES only and
does NOT freeze open positions. Specifically:

  - apply_kill_switch_gate (ENTRY gate) blocks BUY emission on operator
    halt + engine HALT_ALL + engine HALT_MARKET.
  - apply_kill_switch_exit_gate (EXIT gate, new) blocks SELL emission
    only on catastrophic engine HALT_ALL. HALT_MARKET and operator halt
    allow exits through so positions can bleed via ATR / per-trade /
    converge signals.
  - execute() routes BUY through the entry gate and SELL through the
    exit gate (session 8 split).
  - _check_trailing_stops is reachable from run_crypto even when
    operator halt is set (pre-session-8 the runner short-circuited
    BEFORE the trailing-stops call, masking exposure).

Reference: docs/known_issues/2026-05-23_kill_trigger_investigation.md
+ session-7 surfaced finding (.rollback/2026-05-24_session7_kill_alerts_lint/
MANIFEST.txt).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest


# -- shared fixtures ----------------------------------------------------------


@pytest.fixture
def _engine_at_drawdown(monkeypatch, tmp_path):
    """Reset the cached RiskEngine singleton + isolate STATE_FILE per test
    so persisted peaks don't leak between tests. Also stubs the
    standalone-strategy book-value scanner so the engine MTM is not
    polluted by real on-disk state files in data/*_state.json — those
    files inflate or deflate total_equity unpredictably under test.
    Returns the live_paper_runner module.

    The engine's STATE_FILE is computed at import time; without the env
    var override + module-level rebind, all tests in this file would share
    /app/data/state/risk_engine_state.json (or its Windows-fallback
    equivalent), which means the FIRST test that hits HALT_ALL would
    persist `_all_halted` state that contaminates later tests.
    """
    import trading.live_paper_runner as lpr
    import risk.engine as risk_engine

    state_file = tmp_path / "risk_engine_state.json"
    monkeypatch.setenv("AAATS_RISK_STATE_FILE", str(state_file))
    monkeypatch.setattr(risk_engine, "STATE_FILE", state_file)
    monkeypatch.setattr(lpr, "_risk_engine", None)
    # Isolate from real-disk strategy state.
    monkeypatch.setattr(lpr, "_strategy_state_book_value", lambda: 0.0)
    return lpr


def _mk_mkt(capital: float) -> dict:
    """Build a per-market portfolio dict with every key execute() reads.
    Missing keys (e.g. total_loss_pct) blow up the SELL branch even when
    the assertion under test is about the kill gate."""
    return {
        "capital":        capital,
        "peak_equity":    110.0,
        "realized_pnl":   0.0,
        "total_trades":   0,
        "wins":           0,
        "losses":         0,
        "total_win_pct":  0.0,
        "total_loss_pct": 0.0,
    }


@pytest.fixture
def _portfolio_below_kill():
    """Portfolio with capital low enough that the engine's auto-derived
    peak (LOCKED_STARTING_EQUITY=110.0) gives drawdown <= -15% per market
    but NOT <= -20% portfolio. Setting capital to $89 / peak $110 gives
    -19% portfolio (just above the -20% kill) and -19% market (well past
    the -15% kill).
    """
    positions = {"crypto": {}, "india": {}, "us": {}}
    portfolio = {
        "crypto": _mk_mkt(89.0),
        "india":  _mk_mkt(0.0),
        "us":     _mk_mkt(0.0),
    }
    return positions, portfolio


@pytest.fixture
def _portfolio_healthy():
    """Portfolio at full capital — no engine halt regardless of decision."""
    positions = {"crypto": {}, "india": {}, "us": {}}
    portfolio = {
        "crypto": _mk_mkt(110.0),
        "india":  _mk_mkt(0.0),
        "us":     _mk_mkt(0.0),
    }
    return positions, portfolio


# -- 1. ENTRY gate now consults operator halt ---------------------------------


def test_entry_gate_blocks_on_operator_halt(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """When data/halt_state.json says is_halted('crypto')=True, the entry
    gate must return (False, ...) EVEN IF the engine reports no halt.

    Pre-session-8: the entry gate ignored operator halt; only the
    runner-level early-return enforced it. With the early-return removed
    in session 8, the gate must consult is_halted itself."""
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    # Force is_halted to True without touching the real halt file.
    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: True)

    allowed, reason = lpr.apply_kill_switch_gate(
        "crypto", "BTC/USDT", 60_000.0, positions, portfolio,
    )
    assert allowed is False
    assert "operator" in reason.lower()


def test_entry_gate_passes_with_no_halt(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """Sanity check: full capital + no operator halt → entry allowed."""
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: False)

    allowed, _ = lpr.apply_kill_switch_gate(
        "crypto", "BTC/USDT", 60_000.0, positions, portfolio,
    )
    assert allowed is True


# -- 2. EXIT gate ignores operator halt and HALT_MARKET -----------------------


def _stub_decide(action: str, market: str = "crypto", reason: str = ""):
    """Build a fake _mark_to_market_and_decide return value with a
    deterministic action. Lets gate tests control the engine outcome
    without poking at the engine's persisted state."""
    from risk.engine import RiskDecision
    return RiskDecision(action=action, reason=reason or action, market=market)


def test_exit_gate_allows_on_operator_halt(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """Operator halt is a 'block new entries' channel. The exit gate
    MUST allow SELL through even when is_halted is True so open positions
    can bleed via ATR / per-trade stop / signal SELL."""
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: True)
    # Force engine MTM to return ALLOW so we isolate the operator-halt
    # behavior from any engine state.
    monkeypatch.setattr(
        lpr, "_mark_to_market_and_decide",
        lambda *a, **kw: _stub_decide("ALLOW"),
    )

    allowed, _ = lpr.apply_kill_switch_exit_gate(
        "crypto", "BTC/USDT", 60_000.0, positions, portfolio,
    )
    assert allowed is True


def test_exit_gate_allows_on_halt_market(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """Per-market drawdown <= -15% triggers HALT_MARKET on the engine but
    the exit gate must let SELLs through. Only HALT_ALL (portfolio-wide)
    catastrophically blocks exits."""
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: False)
    monkeypatch.setattr(
        lpr, "_mark_to_market_and_decide",
        lambda *a, **kw: _stub_decide("HALT_MARKET", reason="crypto -19% drawdown"),
    )

    allowed, _ = lpr.apply_kill_switch_exit_gate(
        "crypto", "BTC/USDT", 60_000.0, positions, portfolio,
    )
    assert allowed is True, "exit gate must allow SELL under HALT_MARKET"


def test_exit_gate_blocks_on_halt_all(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """The only path that may block an exit is catastrophic engine HALT_ALL
    (portfolio drawdown past -20%). The exit gate must return (False, ...)
    when the engine reports HALT_ALL."""
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: False)
    monkeypatch.setattr(
        lpr, "_mark_to_market_and_decide",
        lambda *a, **kw: _stub_decide(
            "HALT_ALL", reason="portfolio -25% drawdown"
        ),
    )

    allowed, reason = lpr.apply_kill_switch_exit_gate(
        "crypto", "BTC/USDT", 60_000.0, positions, portfolio,
    )
    assert allowed is False
    assert "drawdown" in reason or "halt" in reason.lower()


# -- 3. execute() routes BUY vs SELL through different gates ------------------


def _make_features(rows: int = 60, close: float = 60_000.0) -> pd.DataFrame:
    """Minimal feature frame for execute() — needs columns the BUY / stop
    path will read (atr_14 mostly)."""
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=rows, freq="1h")
    return pd.DataFrame({
        "timestamp": idx,
        "open":   np.full(rows, close),
        "high":   np.full(rows, close * 1.001),
        "low":    np.full(rows, close * 0.999),
        "close":  np.full(rows, close),
        "volume": np.full(rows, 100.0),
        "atr_14": np.full(rows, close * 0.01),
        "rsi_14": np.full(rows, 50.0),
        "macd":   np.zeros(rows),
        "adx_14": np.full(rows, 25.0),
        "ema_50": np.full(rows, close),
        "vol_ratio_20": np.full(rows, 1.0),
    })


def test_execute_sell_fires_through_operator_halt(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """A position that has already been opened must be closeable via
    signal=SELL EVEN when operator halt is set. Pre-session-8 the
    apply_kill_switch_gate at the top of execute() blocked all emissions
    including SELL; post-session-8 the SELL branch routes through the
    exit gate which ignores operator halt.
    """
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    # Seed an open BTC position.
    positions["crypto"]["BTC/USDT"] = {
        "shares":      0.001,
        "entry_price": 60_000.0,
        "entry_time":  datetime.now(timezone.utc).isoformat(),
        "regime":      "RANGE_BOUND",
        "sector":      "",
        "atr_entry":   600.0,
        "risk_pct":    0.01,
    }

    # Operator halt active.
    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: True)

    # Stub record_trade, send_alert, _fill_price so the test does not touch sqlite or Telegram.
    monkeypatch.setattr(lpr, "record_trade", lambda *a, **kw: None)
    monkeypatch.setattr(lpr, "send_alert",   lambda *a, **kw: None)

    feat = _make_features()
    lpr.execute(
        market="crypto", symbol="BTC/USDT", signal="SELL",
        regime="RANGE_BOUND", confidence=0.6,
        last_price=61_000.0,                 # +1.7% — winning SELL
        features=feat,
        positions=positions, portfolio=portfolio,
    )

    assert "BTC/USDT" not in positions["crypto"], (
        "SELL was blocked despite operator halt — exit gate not wired"
    )


def test_execute_buy_blocked_by_operator_halt(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """The corresponding BUY must be blocked. This is the intentional
    side of the gap: operator halt blocks new entries."""
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: True)

    monkeypatch.setattr(lpr, "record_trade", lambda *a, **kw: None)
    monkeypatch.setattr(lpr, "send_alert",   lambda *a, **kw: None)

    feat = _make_features()
    lpr.execute(
        market="crypto", symbol="BTC/USDT", signal="BUY",
        regime="RANGE_BOUND", confidence=0.6,
        last_price=60_000.0,
        features=feat,
        positions=positions, portfolio=portfolio,
    )

    assert "BTC/USDT" not in positions["crypto"], (
        "BUY was permitted under operator halt — entry gate not wired"
    )


def test_execute_sell_fires_through_halt_market(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """Engine in HALT_MARKET (per-market drawdown <= -15%) must NOT block
    SELL. Pre-session-8 apply_kill_switch_gate blocked all execute()
    emissions on HALT_MARKET; post-session-8 only HALT_ALL blocks SELL.
    """
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    positions["crypto"]["BTC/USDT"] = {
        "shares":      0.001,
        "entry_price": 60_000.0,
        "entry_time":  datetime.now(timezone.utc).isoformat(),
        "regime":      "RANGE_BOUND",
        "sector":      "",
        "atr_entry":   600.0,
        "risk_pct":    0.01,
    }

    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: False)
    # Force engine into HALT_MARKET decision without depending on real DD.
    monkeypatch.setattr(
        lpr, "_mark_to_market_and_decide",
        lambda *a, **kw: _stub_decide("HALT_MARKET", reason="crypto -18% DD"),
    )

    monkeypatch.setattr(lpr, "record_trade", lambda *a, **kw: None)
    monkeypatch.setattr(lpr, "send_alert",   lambda *a, **kw: None)

    feat = _make_features()
    lpr.execute(
        market="crypto", symbol="BTC/USDT", signal="SELL",
        regime="RANGE_BOUND", confidence=0.6,
        last_price=58_800.0,                 # -2% — per-trade stop level
        features=feat,
        positions=positions, portfolio=portfolio,
    )

    assert "BTC/USDT" not in positions["crypto"], (
        "SELL was blocked on HALT_MARKET — exit gate semantics wrong"
    )


# -- 4. run_crypto reaches _check_trailing_stops despite operator halt --------


def test_run_crypto_reaches_trailing_stops_on_operator_halt(
    _engine_at_drawdown, _portfolio_healthy, monkeypatch
):
    """Pre-session-8 fix: run_crypto returned at line ~1583 on
    is_halted('crypto')=True. _check_trailing_stops was never called, so
    open positions silently accumulated stale pnl. Post-fix:
    _check_trailing_stops MUST be invoked even when operator halt is set.

    We assert via monkeypatch that _check_trailing_stops is called at
    least once when run_crypto is invoked with operator halt active.
    """
    lpr = _engine_at_drawdown
    positions, portfolio = _portfolio_healthy

    import foundation.kill_switch as ks
    monkeypatch.setattr(ks, "is_halted", lambda market: True)

    # Make Binance / data fetches no-ops so the cycle proceeds without
    # touching the network.
    monkeypatch.setattr(lpr, "_binance_healthy",  lambda: True)
    monkeypatch.setattr(lpr, "fetch_btc_dominance", lambda: 50.0)
    monkeypatch.setattr(lpr, "fetch_crypto_hourly", lambda sym: None)
    monkeypatch.setattr(lpr, "_regime_is_stale",   lambda sym: False)
    monkeypatch.setattr(lpr, "save_positions",     lambda *a, **kw: None)
    monkeypatch.setattr(lpr, "save_portfolio",     lambda *a, **kw: None)
    monkeypatch.setattr(lpr, "send_alert",         lambda *a, **kw: None)

    # Record the call.
    calls: list[tuple] = []
    real_check = lpr._check_trailing_stops

    def _spy(market, last_prices, features_map, positions, portfolio):
        calls.append((market, dict(last_prices)))
        return real_check(market, last_prices, features_map, positions, portfolio)

    monkeypatch.setattr(lpr, "_check_trailing_stops", _spy)

    # Stub the standalone strategies so the test does not touch any of
    # their state files.
    for name in (
        "run_strategy_with_isolation",
    ):
        monkeypatch.setattr(lpr, name, lambda *a, **kw: None)

    lpr.run_crypto(positions, portfolio)

    assert len(calls) == 1, (
        f"_check_trailing_stops was not called during run_crypto under "
        f"operator halt — runner is still short-circuiting (calls={calls})"
    )
    assert calls[0][0] == "crypto"


# -- 5. C3/C6 exit paths now use the exit gate, not the entry gate ------------


def test_c3_resolves_exit_gate_alias():
    """C3's run_altcoin_reversion_crypto must import
    apply_kill_switch_exit_gate. Pre-session-8 it only imported
    apply_kill_switch_gate, which would have meant HALT_MARKET still
    blocked the SELL path."""
    import trading.altcoin_reversion as c3
    import inspect

    src = inspect.getsource(c3.run_altcoin_reversion_crypto)
    assert "apply_kill_switch_exit_gate" in src, (
        "C3 does not import the new exit gate; SELL path still on entry gate"
    )
    assert "_exit_gate_check" in src, (
        "C3 SELL branch must consult _exit_gate_check"
    )


def test_c6_resolves_exit_gate_alias():
    """C6 bollinger_range — same constraint as C3."""
    import trading.bollinger_range as c6
    import inspect

    src = inspect.getsource(c6.run_bollinger_range_crypto)
    assert "apply_kill_switch_exit_gate" in src
    assert "_exit_gate_check" in src


def test_c1_run_pair_accepts_exit_gate_check():
    """C1 stat_arb._run_pair must accept exit_gate_check kwarg (separate
    from gate_check) and use it for CONVERGE / HARD_STOP / TIME_STOP."""
    import trading.stat_arb as c1
    import inspect

    sig = inspect.signature(c1._run_pair)
    assert "exit_gate_check" in sig.parameters, (
        "C1 _run_pair must accept exit_gate_check kwarg"
    )
