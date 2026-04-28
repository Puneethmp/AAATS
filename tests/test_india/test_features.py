"""
Tests for markets/india/feature_engineer.py.
No network calls — all TA computed in-memory from synthetic DataFrames.
"""

import numpy as np
import pandas as pd
import pytest

from markets.india.feature_engineer import engineer_features, _EXPECTED_OUTPUT_COLUMNS

# ── Helpers ───────────────────────────────────────────────────────────────────

_INDIA_VIX = 14.5
_FII_NET = 1200.0
_DII_NET = -300.0


def _make_ohlcv(n: int = 300, seed: int = 99) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with a random-walk price series."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0, 0.01, n)
    closes = 100.0 * np.cumprod(1 + returns) if n > 0 else np.array([])
    opens = closes * (1 + rng.normal(0, 0.003, n)) if n > 0 else np.array([])
    highs = (
        np.maximum(opens, closes) * (1 + rng.uniform(0, 0.005, n))
        if n > 0
        else np.array([])
    )
    lows = (
        np.minimum(opens, closes) * (1 - rng.uniform(0, 0.005, n))
        if n > 0
        else np.array([])
    )
    volumes = rng.integers(500_000, 5_000_000, n).astype(float) if n > 0 else np.array([])
    timestamps = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestEngineerFeatures:
    def test_all_expected_columns_present(self):
        """Output must contain every column defined in the spec."""
        df = _make_ohlcv(300)
        result = engineer_features(df, "SBIN", _INDIA_VIX, _FII_NET, _DII_NET, config=None)
        assert not result.empty
        for col in _EXPECTED_OUTPUT_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    def test_rsi_bounded(self):
        """RSI must be in [0, 100] for all non-NaN rows."""
        df = _make_ohlcv(300)
        result = engineer_features(df, "RELIANCE", _INDIA_VIX, _FII_NET, _DII_NET, config=None)
        rsi_valid = result["rsi_14"].dropna()
        assert not rsi_valid.empty
        assert (rsi_valid >= 0).all(), "RSI below 0 found"
        assert (rsi_valid <= 100).all(), "RSI above 100 found"

    def test_atr_positive(self):
        """ATR must be positive for all non-NaN rows (random-walk data always has movement)."""
        df = _make_ohlcv(300)
        result = engineer_features(df, "TCS", _INDIA_VIX, _FII_NET, _DII_NET, config=None)
        atr_valid = result["atr_14"].dropna()
        assert not atr_valid.empty
        assert (atr_valid > 0).all(), "ATR contains non-positive values"

    def test_ema200_nan_for_insufficient_rows(self):
        """EMA_200 must be NaN when fewer than 200 bars are present — no crash."""
        df = _make_ohlcv(100)  # only 100 rows — EMA_200 can never be computed
        result = engineer_features(df, "INFY", _INDIA_VIX, _FII_NET, _DII_NET, config=None)
        assert result["ema_200"].isna().all(), (
            "EMA_200 should be all-NaN when input has fewer than 200 bars"
        )
        assert len(result) == 100, "Warmup rows must be retained, not dropped"

    def test_fii_dii_appended_correctly(self):
        """FII and DII scalar values must be broadcast identically to every row."""
        df = _make_ohlcv(250)
        result = engineer_features(df, "HDFC", _INDIA_VIX, _FII_NET, _DII_NET, config=None)
        assert (result["fii_net"] == _FII_NET).all(), "fii_net not broadcast correctly"
        assert (result["dii_net"] == _DII_NET).all(), "dii_net not broadcast correctly"
        assert (result["india_vix"] == _INDIA_VIX).all(), "india_vix not broadcast correctly"

    def test_empty_dataframe_returns_empty_with_schema(self):
        """Empty input must return empty DataFrame with correct columns — no exception."""
        empty = pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        result = engineer_features(empty, "WIPRO", _INDIA_VIX, _FII_NET, _DII_NET, config=None)
        assert result.empty, "Result should be empty for empty input"
        for col in _EXPECTED_OUTPUT_COLUMNS:
            assert col in result.columns, f"Empty result missing column: {col}"

    def test_no_lookahead_rsi(self):
        """
        RSI at bar T computed on the full series must equal RSI on df[:T+1].
        Verifies no future data bleeds backward through any indicator.
        """
        df = _make_ohlcv(300)
        result_full = engineer_features(
            df.copy(), "TEST", _INDIA_VIX, _FII_NET, _DII_NET, config=None
        )

        T = 270  # well past the warmup period
        ts_at_T = df.iloc[T]["timestamp"]

        full_row = result_full[result_full["timestamp"] == ts_at_T]
        assert not full_row.empty, "Row T not found in full result (check warmup cutoff)"

        result_partial = engineer_features(
            df.iloc[: T + 1].copy(), "TEST", _INDIA_VIX, _FII_NET, _DII_NET, config=None
        )

        full_val = full_row["rsi_14"].iloc[0]
        partial_val = result_partial.iloc[-1]["rsi_14"]
        assert abs(full_val - partial_val) < 1e-6, (
            f"Lookahead detected in RSI: full={full_val:.6f}, partial={partial_val:.6f}"
        )
