"""
C1 stat_arb standalone kill-gate test (session 7).

Asserts that when the kill-switch gate is wired AND tripped (e.g. paper-crypto
sitting at -33% portfolio drawdown), run_stat_arb_crypto does NOT open a new
position even when |z| > entry_z and the pair-health gate would otherwise pass.

Pre-patch (session 6 and earlier): run_stat_arb_crypto did not accept
full_positions / full_portfolio kwargs and never consulted apply_kill_switch_gate.
Test would fail with TypeError on the call signature.

Post-patch (session 7): the gate is resolved at the top of run_stat_arb_crypto
and consulted before any BUY emission in _run_pair's entry block, parity with
C3 (altcoin_reversion.py) and C6 (bollinger_range.py).

Reference: docs/known_issues/2026-05-23_kill_trigger_investigation.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest


def _make_stretched_pair(
    rows: int = 80, base_a: float = 60000.0, base_b: float = 4000.0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a pair where the log spread blows out at the tail so |z| > 1.8
    on the trailing 30-bar window (pair.entry_z).

    BTC stays roughly flat at base_a. ETH plunges in the final 10 bars, which
    makes log(BTC) - log(ETH) rise sharply -> very positive z-score -> entry
    signal triggers SHORT_A (sell BTC leg)."""
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=rows, freq="1h")
    a_close = np.full(rows, base_a) + np.random.RandomState(7).normal(0, 5, rows)
    b_close = np.full(rows, base_b)
    # Plunge ETH in the final 10 bars to stretch the spread.
    b_close[-10:] = np.linspace(base_b, base_b * 0.7, 10)
    df_a = pd.DataFrame(
        {
            "timestamp": idx,
            "open": a_close,
            "high": a_close + 1,
            "low": a_close - 1,
            "close": a_close,
            "volume": np.ones(rows),
        }
    )
    df_b = pd.DataFrame(
        {
            "timestamp": idx,
            "open": b_close,
            "high": b_close + 1,
            "low": b_close - 1,
            "close": b_close,
            "volume": np.ones(rows),
        }
    )
    return df_a, df_b


@pytest.fixture
def _stat_arb_module(monkeypatch, tmp_path):
    """Isolate state file + health cache to tmp_path; patch _record so the
    test does not touch the live paper_trades.db."""
    from trading import stat_arb as sa

    monkeypatch.setattr(sa, "_STATE_FILE", tmp_path / "stat_arb_state.json")
    monkeypatch.setattr(sa, "_HEALTH_FILE", tmp_path / "stat_arb_health.json")
    # Seed pair health as fresh + healthy so the cache won't be re-computed.
    healthy_cache = {
        "BTC/USDT_ETH/USDT": {
            "eg_pvalue": 0.001,
            "corr_14d": 0.95,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "pair_healthy": True,
        }
    }
    (tmp_path / "stat_arb_health.json").write_text(
        __import__("json").dumps(healthy_cache)
    )
    # Stub the trade-record sink so we don't touch sqlite.
    monkeypatch.setattr(sa, "_record_stat_arb_trade", lambda *a, **kw: None)
    # Silence Telegram.
    monkeypatch.setattr(sa, "_send", lambda *a, **kw: None)
    # These tests exercise the kill-switch gate on the ENTRY path, so the
    # research-bed demotion (ENTRIES_DISABLED, 2026-06-10) must be lifted —
    # otherwise every entry is blocked before the gate under test runs.
    monkeypatch.setattr(sa, "ENTRIES_DISABLED", False)
    return sa


def _make_portfolio_at_drawdown() -> tuple[dict, dict]:
    """Paper-crypto portfolio sitting at $87 / peak $131 = -33% drawdown.
    Mirrors the live state captured in session-7 deploy 2026-05-24 (see
    .rollback/2026-05-24_session7_kill_alerts_lint/MANIFEST.txt)."""
    positions = {"crypto": {}, "india": {}, "us": {}}
    portfolio = {
        "crypto": {
            "capital": 87.45,
            "peak_equity": 131.32,
            "realized_pnl": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
        },
        "india": {"capital": 0.0},
        "us": {"capital": 0.0},
    }
    return positions, portfolio


def test_signature_accepts_full_positions_full_portfolio(_stat_arb_module):
    """Session-7 wire: run_stat_arb_crypto must accept full_positions and
    full_portfolio kwargs. Pre-patch this raised TypeError; post-patch it
    is a no-op when the fetch returns None (data unavailable)."""
    sa = _stat_arb_module
    positions, portfolio = _make_portfolio_at_drawdown()
    # Fetch returns None -> early-skip -> no state mutation.
    sa.run_stat_arb_crypto(
        portfolio,
        fetch_hourly_fn=lambda sym: None,
        full_positions=positions,
        full_portfolio=portfolio,
    )
    assert sa._load_state() == {}


def test_kill_gate_blocks_entry_at_drawdown(_stat_arb_module, monkeypatch):
    """At -33% drawdown with the kill gate tripped, a stretched spread
    must NOT open a position."""
    sa = _stat_arb_module
    positions, portfolio = _make_portfolio_at_drawdown()
    df_a, df_b = _make_stretched_pair()

    # Sanity: the synthetic data really does cross the entry-z threshold.
    pair = next(p for p in sa.PAIRS if p.market == "crypto")
    _spread, _z = sa._compute_spread_zscore(df_a["close"], df_b["close"], pair.window)
    assert (
        abs(_z) > pair.entry_z
    ), f"fixture broken: |z|={abs(_z):.3f} should exceed entry_z={pair.entry_z}"

    # Patch the runner's gate to always block — simulates HALT_MARKET /
    # HALT_ALL decision from RiskEngine.update_market at <-15% drawdown.
    import trading.live_paper_runner as lpr

    monkeypatch.setattr(
        lpr,
        "apply_kill_switch_gate",
        lambda market, symbol, last_price, positions, portfolio: (
            False,
            "TEST_HALT_MARKET_DD",
        ),
    )

    sa.run_stat_arb_crypto(
        portfolio,
        fetch_hourly_fn=lambda sym: df_a if "BTC" in sym else df_b,
        full_positions=positions,
        full_portfolio=portfolio,
    )

    # Assert: no position opened, capital unchanged.
    state = sa._load_state()
    assert state == {}, f"kill gate failed — position opened: {state}"
    assert portfolio["crypto"]["capital"] == pytest.approx(
        87.45
    ), "capital was debited despite kill gate blocking entry"
    assert portfolio["crypto"]["total_trades"] == 0


def test_kill_gate_open_allows_entry(_stat_arb_module, monkeypatch):
    """Inverse check: when gate returns (True, ""), the stretched spread
    DOES open a position. Confirms the gate is the only thing blocking
    in the prior test (i.e. the fixture is not silently failing the
    pair-health / capital / threshold checks)."""
    sa = _stat_arb_module
    positions, portfolio = _make_portfolio_at_drawdown()
    df_a, df_b = _make_stretched_pair()

    import trading.live_paper_runner as lpr

    monkeypatch.setattr(
        lpr,
        "apply_kill_switch_gate",
        lambda market, symbol, last_price, positions, portfolio: (True, ""),
    )

    sa.run_stat_arb_crypto(
        portfolio,
        fetch_hourly_fn=lambda sym: df_a if "BTC" in sym else df_b,
        full_positions=positions,
        full_portfolio=portfolio,
    )

    state = sa._load_state()
    assert "BTC/USDT_ETH/USDT" in state, (
        f"gate-open path did NOT open a position: state={state}. "
        "Fixture or health-gate may be silently skipping."
    )
    assert portfolio["crypto"]["capital"] < 87.45, "capital was not debited on entry"


def test_back_compat_no_gate_when_kwargs_missing(_stat_arb_module):
    """Without full_positions / full_portfolio, the gate must be bypassed
    (test / standalone callers). Existing call sites in test suites that
    don't pass these kwargs must continue to work."""
    sa = _stat_arb_module
    positions, portfolio = _make_portfolio_at_drawdown()
    df_a, df_b = _make_stretched_pair()

    sa.run_stat_arb_crypto(
        portfolio,
        fetch_hourly_fn=lambda sym: df_a if "BTC" in sym else df_b,
        # full_positions/full_portfolio omitted -> gate bypassed entirely.
    )

    # Without the gate, the stretched spread should open the position.
    state = sa._load_state()
    assert (
        "BTC/USDT_ETH/USDT" in state
    ), f"back-compat path (no gate kwargs) failed to open position: state={state}"
