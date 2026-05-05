"""Tests for markets/crypto/integration.py."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from markets.crypto.integration import (
    CryptoConfig,
    CryptoMarketSnapshot,
    _compute_basic_features,
    get_crypto_regime_summary,
    run_all_symbols,
    run_data_cycle,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 250, start_price: float = 30_000.0) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame for tests."""
    import numpy as np

    rng = np.random.default_rng(42)
    prices = start_price + rng.standard_normal(n).cumsum() * 200
    prices = prices.clip(min=100)

    from datetime import datetime, timezone
    end_ts = datetime.now(timezone.utc)
    timestamps = pd.date_range(end=end_ts, periods=n, freq="h", tz="UTC")
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open":   prices * (1 - 0.001),
        "high":   prices * (1 + 0.005),
        "low":    prices * (1 - 0.005),
        "close":  prices,
        "volume": rng.uniform(100, 1000, n),
    })
    return df


def _mock_fetcher(symbol, timeframe, start, end):
    return _make_ohlcv(250)


def _empty_fetcher(symbol, timeframe, start, end):
    return pd.DataFrame()


# ── CryptoConfig ──────────────────────────────────────────────────────────────

class TestCryptoConfig:
    def test_defaults(self):
        cfg = CryptoConfig()
        assert "BTC/USDT" in cfg.symbols
        assert "ETH/USDT" in cfg.symbols
        assert cfg.timeframe == "1Hour"
        assert cfg.lookback_hours == 200
        assert cfg.capital_usdt == 10_000.0
        assert cfg.max_drawdown_pct == 0.25

    def test_custom_symbols(self):
        cfg = CryptoConfig(symbols=["SOL/USDT"])
        assert cfg.symbols == ["SOL/USDT"]

    def test_custom_db_path(self):
        cfg = CryptoConfig(db_path="/tmp/test.db")
        assert cfg.db_path == "/tmp/test.db"


# ── _compute_basic_features ───────────────────────────────────────────────────

class TestComputeBasicFeatures:
    def setup_method(self):
        self.df = _make_ohlcv(300)

    def test_returns_columns_present(self):
        out = _compute_basic_features(self.df)
        for col in ("return_1d", "return_5d"):
            assert col in out.columns

    def test_ema_columns_present(self):
        out = _compute_basic_features(self.df)
        for col in ("ema_50", "ema_200", "ema_spread_pct"):
            assert col in out.columns

    def test_rsi_bounded(self):
        out = _compute_basic_features(self.df)
        valid = out["rsi_14"].dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_atr_non_negative(self):
        out = _compute_basic_features(self.df)
        assert (out["atr_14"].dropna() >= 0).all()

    def test_macd_present(self):
        out = _compute_basic_features(self.df)
        assert "macd" in out.columns

    def test_vol_ratio_present(self):
        out = _compute_basic_features(self.df)
        assert "vol_ratio" in out.columns

    def test_input_unchanged(self):
        original_cols = set(self.df.columns)
        _compute_basic_features(self.df)
        assert set(self.df.columns) == original_cols

    def test_output_same_length(self):
        out = _compute_basic_features(self.df)
        assert len(out) == len(self.df)


# ── run_data_cycle ────────────────────────────────────────────────────────────

class TestRunDataCycle:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = CryptoConfig(
            db_path=str(Path(self.tmp) / "test_crypto.db"),
            lookback_hours=200,
        )

    def test_returns_snapshot(self):
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        assert isinstance(snap, CryptoMarketSnapshot)

    def test_symbol_preserved(self):
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        assert snap.symbol == "BTC/USDT"

    def test_timeframe_preserved(self):
        snap = run_data_cycle("ETH/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        assert snap.timeframe == self.cfg.timeframe

    def test_regime_is_string(self):
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        assert isinstance(snap.regime, str)
        assert len(snap.regime) > 0

    def test_latest_bar_not_empty(self):
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        assert isinstance(snap.latest_bar, dict)
        assert "close" in snap.latest_bar

    def test_bars_stored_positive(self):
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        assert snap.bars_stored > 0

    def test_feature_cols_non_empty(self):
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        assert len(snap.feature_cols) > 0

    def test_no_error_on_success(self):
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        assert snap.error is None

    def test_empty_fetch_with_no_db_data(self):
        # Fetcher returns nothing and DB is empty → UNKNOWN snapshot
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_empty_fetcher)
        assert snap.regime == "UNKNOWN"
        assert snap.bars_stored == 0

    def test_error_returns_unknown_snapshot(self):
        def bad_fetcher(symbol, timeframe, start, end):
            raise RuntimeError("simulated network failure")

        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=bad_fetcher)
        assert snap.regime == "UNKNOWN"
        assert snap.error is not None
        assert "simulated network failure" in snap.error

    def test_valid_regime_values(self):
        snap = run_data_cycle("BTC/USDT", self.cfg, fetcher_fn=_mock_fetcher)
        valid = {"BULL_TREND", "BEAR_TREND", "RANGE_BOUND", "HIGH_VOLATILITY", "UNKNOWN"}
        assert snap.regime in valid


# ── run_all_symbols ───────────────────────────────────────────────────────────

class TestRunAllSymbols:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = CryptoConfig(
            symbols=["BTC/USDT", "ETH/USDT"],
            db_path=str(Path(self.tmp) / "test_all.db"),
        )

    def test_returns_list(self):
        result = run_all_symbols(self.cfg, fetcher_fn=_mock_fetcher)
        assert isinstance(result, list)

    def test_one_snapshot_per_symbol(self):
        result = run_all_symbols(self.cfg, fetcher_fn=_mock_fetcher)
        assert len(result) == len(self.cfg.symbols)

    def test_symbols_match_config(self):
        result = run_all_symbols(self.cfg, fetcher_fn=_mock_fetcher)
        symbols = [s.symbol for s in result]
        assert set(symbols) == set(self.cfg.symbols)

    def test_all_snapshots_are_instances(self):
        result = run_all_symbols(self.cfg, fetcher_fn=_mock_fetcher)
        for snap in result:
            assert isinstance(snap, CryptoMarketSnapshot)

    def test_single_symbol_config(self):
        cfg = CryptoConfig(
            symbols=["BTC/USDT"],
            db_path=str(Path(self.tmp) / "single.db"),
        )
        result = run_all_symbols(cfg, fetcher_fn=_mock_fetcher)
        assert len(result) == 1
        assert result[0].symbol == "BTC/USDT"


# ── get_crypto_regime_summary ─────────────────────────────────────────────────

class TestGetCryptoRegimeSummary:
    def test_returns_dict(self):
        snaps = [
            CryptoMarketSnapshot("BTC/USDT", "1Hour", "BULL_TREND", {}, 10, []),
            CryptoMarketSnapshot("ETH/USDT", "1Hour", "RANGE_BOUND", {}, 10, []),
        ]
        summary = get_crypto_regime_summary(snaps)
        assert isinstance(summary, dict)

    def test_keys_are_symbols(self):
        snaps = [
            CryptoMarketSnapshot("BTC/USDT", "1Hour", "BULL_TREND", {}, 10, []),
            CryptoMarketSnapshot("ETH/USDT", "1Hour", "BEAR_TREND", {}, 10, []),
        ]
        summary = get_crypto_regime_summary(snaps)
        assert "BTC/USDT" in summary
        assert "ETH/USDT" in summary

    def test_values_are_regimes(self):
        snaps = [
            CryptoMarketSnapshot("BTC/USDT", "1Hour", "BULL_TREND", {}, 10, []),
        ]
        summary = get_crypto_regime_summary(snaps)
        assert summary["BTC/USDT"] == "BULL_TREND"

    def test_empty_list(self):
        summary = get_crypto_regime_summary([])
        assert summary == {}

    def test_unknown_regime_preserved(self):
        snaps = [
            CryptoMarketSnapshot("BTC/USDT", "1Hour", "UNKNOWN", {}, 0, [], error="err"),
        ]
        summary = get_crypto_regime_summary(snaps)
        assert summary["BTC/USDT"] == "UNKNOWN"
