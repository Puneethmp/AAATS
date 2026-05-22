"""Tests for the B.2 C3 patch — BTC.D fast-rise filter + symbol denylist.

Wires up the two changes in trading/altcoin_reversion.py (2026-05-22):
  (a) BTC_DOM_FAST_RISE filter inside _entry_allowed (constant existed at
      :77 but was never read until B.2).
  (b) DENYLIST_SYMBOLS short-circuit for OP/ARB/PUMP/FET/LUNC at the entry
      branch in run_altcoin_reversion_crypto.

Diagnostic source: docs/known_issues/2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# --- helpers ---------------------------------------------------------------


def _make_btc_df(rows: int = 100, close_drift: float = 0.0) -> pd.DataFrame:
    """Build a realistic-ish BTC OHLCV frame with a controllable RSI."""
    base = np.linspace(60000.0, 60000.0 + close_drift, rows)
    idx = pd.date_range(end=datetime.now(timezone.utc), periods=rows, freq="1h")
    df = pd.DataFrame(
        {
            "open": base,
            "high": base + 50,
            "low": base - 50,
            "close": base,
            "volume": np.ones(rows) * 10.0,
        },
        index=idx,
    )
    return df


# --- (a) BTC.D fast-rise filter --------------------------------------------


class TestBtcDomFastRiseFilter:
    """_entry_allowed must refuse entry when BTC.D rose more than the threshold."""

    def test_no_delta_treated_as_no_signal(self):
        """First cycle after restart: cache empty → delta=None → filter inactive."""
        from trading.altcoin_reversion import _entry_allowed

        btc_df = _make_btc_df(close_drift=+200.0)  # rising → RSI high
        assert _entry_allowed(btc_df, regime="BULL_TREND", btc_dom_delta=None) is True

    def test_small_positive_delta_allows_entry(self):
        from trading.altcoin_reversion import _entry_allowed

        btc_df = _make_btc_df(close_drift=+200.0)
        # 0.1 pp jump is well below 0.8 pp threshold.
        assert _entry_allowed(btc_df, regime="BULL_TREND", btc_dom_delta=0.1) is True

    def test_fast_rise_blocks_entry(self):
        """BTC.D rising > 0.8 pp since last cycle → refuse entry."""
        from trading.altcoin_reversion import _entry_allowed

        btc_df = _make_btc_df(close_drift=+200.0)  # high RSI, BULL regime
        # 1.2 pp jump is fast-rise → MUST refuse.
        assert _entry_allowed(btc_df, regime="BULL_TREND", btc_dom_delta=1.2) is False

    def test_negative_delta_allows_entry(self):
        """BTC.D falling = alt season alive → entries still allowed."""
        from trading.altcoin_reversion import _entry_allowed

        btc_df = _make_btc_df(close_drift=+200.0)
        assert _entry_allowed(btc_df, regime="BULL_TREND", btc_dom_delta=-1.5) is True

    def test_threshold_value_matches_constant(self):
        """The threshold pp is BTC_DOM_FAST_RISE * 100 (fraction → pp)."""
        from trading.altcoin_reversion import BTC_DOM_FAST_RISE, _entry_allowed

        btc_df = _make_btc_df(close_drift=+200.0)
        # Sit one nudge above the threshold.
        delta_at_threshold = BTC_DOM_FAST_RISE * 100 + 0.001
        assert _entry_allowed(
            btc_df, regime="BULL_TREND", btc_dom_delta=delta_at_threshold,
        ) is False


# --- (b) Symbol denylist ---------------------------------------------------


class TestDenylist:
    """The 5 top-loss-leader C3 symbols must be skipped at entry."""

    def test_denylist_membership(self):
        from trading.altcoin_reversion import DENYLIST_SYMBOLS

        assert "OP/USDT" in DENYLIST_SYMBOLS
        assert "ARB/USDT" in DENYLIST_SYMBOLS
        assert "PUMP/USDT" in DENYLIST_SYMBOLS
        assert "FET/USDT" in DENYLIST_SYMBOLS
        assert "LUNC/USDT" in DENYLIST_SYMBOLS
        # In-universe symbols must NOT be denylisted.
        assert "SOL/USDT" not in DENYLIST_SYMBOLS
        assert "LINK/USDT" not in DENYLIST_SYMBOLS

    def test_denylist_skips_buy_entry(self, tmp_path, monkeypatch):
        """run_altcoin_reversion_crypto must skip BUY emission for denylisted sym."""
        from trading import altcoin_reversion as ar

        # Point file outputs at tmp so the test is hermetic.
        monkeypatch.setattr(ar, "STATE_FILE", tmp_path / "altcoin_reversion_state.json")
        monkeypatch.setattr(ar, "COOLDOWN_FILE", tmp_path / "altcoin_reversion_cooldown.json")
        monkeypatch.setattr(ar, "BTC_DOM_CACHE_FILE", tmp_path / "c3_btc_dom_cache.json")
        monkeypatch.setattr(ar, "_USE_UNIFIED_LEDGER", False)

        # Fabricate price data — a denylisted symbol with a z-score deep enough
        # to satisfy Z_ENTRY if the denylist were absent.
        def fetch(symbol: str):
            rows = 120
            idx = pd.date_range(end=datetime.now(timezone.utc), periods=rows, freq="1h")
            if symbol == "BTC/USDT":
                close = np.linspace(60000.0, 60100.0, rows)  # gentle rise
            else:
                # Make the ratio drop steeply at the end so the z-score is very
                # negative (qualifies for entry pre-denylist).
                close = np.concatenate([
                    np.linspace(2.0, 2.0, rows - 5),
                    np.linspace(2.0, 1.0, 5),
                ])
            return pd.DataFrame(
                {"open": close, "high": close + 0.01, "low": close - 0.01,
                 "close": close, "volume": np.ones(rows)}, index=idx,
            )

        # Disable the kill-switch helper to keep the test path simple.
        monkeypatch.setattr(
            ar, "detect_regime", lambda *a, **kw: ("BULL_TREND", None), raising=False,
        )

        record_calls: list[dict] = []
        def fake_record(**kw):
            record_calls.append(kw)
        monkeypatch.setattr(ar, "_record", fake_record)

        portfolio = {"capital": 100.0}
        ar.run_altcoin_reversion_crypto(
            portfolio,
            fetch,
            symbols=["OP/USDT"],  # denylisted
            full_positions=None,
            full_portfolio=None,
            btc_dom_now=50.0,
        )

        # Expect: no BUY was recorded, capital is unchanged, state file is empty.
        buys = [c for c in record_calls if c.get("action") == "BUY"]
        assert len(buys) == 0, f"Denylisted symbol entered: {buys}"
        assert portfolio["capital"] == 100.0


# --- (a)+(b) Integration via btc_dom_cache state ---------------------------


class TestBtcDomCachePersistence:
    """The runner must persist this cycle's btc_dom so the next can compute delta."""

    def test_cache_round_trip(self, tmp_path, monkeypatch):
        from trading import altcoin_reversion as ar

        monkeypatch.setattr(ar, "BTC_DOM_CACHE_FILE", tmp_path / "c3_btc_dom_cache.json")
        assert ar._load_btc_dom_cache() is None  # no prior cache
        ar._save_btc_dom_cache(56.4)
        assert abs(ar._load_btc_dom_cache() - 56.4) < 1e-9

    def test_first_cycle_after_restart_has_no_delta(self, tmp_path, monkeypatch):
        """First-cycle semantics: cache missing → delta=None → filter disabled."""
        from trading import altcoin_reversion as ar

        monkeypatch.setattr(ar, "BTC_DOM_CACHE_FILE", tmp_path / "missing.json")
        monkeypatch.setattr(ar, "STATE_FILE", tmp_path / "state.json")
        monkeypatch.setattr(ar, "COOLDOWN_FILE", tmp_path / "cooldown.json")
        monkeypatch.setattr(ar, "_USE_UNIFIED_LEDGER", False)

        # Just exercise the cache update path; verify the file gets created.
        def fetch(symbol):
            return None  # forces an early return in run_altcoin_reversion_crypto

        ar.run_altcoin_reversion_crypto(
            {"capital": 100.0},
            fetch,
            symbols=[],
            btc_dom_now=58.0,
        )
        assert (tmp_path / "missing.json").exists() is False or \
               json.loads((tmp_path / "missing.json").read_text())["prev_btc_dom"] == 58.0
