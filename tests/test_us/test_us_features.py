"""
Tests for markets/us/feature_engineer.py.
No network calls — purely in-memory DataFrame operations.
"""

import numpy as np
import pandas as pd
import pytest

from markets.us.feature_engineer import calculate_features, _EXPECTED_OUTPUT_COLUMNS


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_ohlcv(n: int = 250, seed: int = 42) -> pd.DataFrame:
    """Generate a synthetic OHLCV DataFrame with a random walk for prices."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0, 0.01, n)
    closes = 100.0 * np.cumprod(1 + returns)
    opens = closes * (1 + rng.normal(0, 0.003, n))
    highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.005, n))
    lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.005, n))
    volumes = rng.integers(500_000, 5_000_000, n).astype(float)
    timestamps = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")

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


class TestCalculateFeatures:
    def test_all_columns_present(self):
        """Output must contain every column defined in the spec."""
        df = _make_ohlcv(250)
        result = calculate_features(df, "AAPL")
        assert not result.empty
        for col in _EXPECTED_OUTPUT_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_lookahead_rsi(self):
        """RSI value at bar T using full DataFrame must equal RSI on df[:T+1]."""
        df = _make_ohlcv(250)
        result_full = calculate_features(df.copy(), "TEST")

        # Pick a row well past the warmup period
        T = 220
        ts_at_T = df.iloc[T]["timestamp"]

        # Confirm that row survived warmup in the full result
        full_row = result_full[result_full["timestamp"] == ts_at_T]
        assert not full_row.empty, "Row T dropped as warmup — increase n or lower T"

        result_partial = calculate_features(df.iloc[: T + 1].copy(), "TEST")

        full_val = full_row["rsi_14"].iloc[0]
        partial_val = result_partial.iloc[-1]["rsi_14"]
        assert abs(full_val - partial_val) < 1e-6, (
            f"Lookahead detected in RSI: full={full_val:.6f}, partial={partial_val:.6f}"
        )

    def test_no_lookahead_ema_20(self):
        """EMA-20 value at bar T using full DataFrame must equal EMA-20 on df[:T+1]."""
        df = _make_ohlcv(250)
        result_full = calculate_features(df.copy(), "TEST")

        T = 220
        ts_at_T = df.iloc[T]["timestamp"]

        full_row = result_full[result_full["timestamp"] == ts_at_T]
        assert not full_row.empty, "Row T dropped as warmup — increase n or lower T"

        result_partial = calculate_features(df.iloc[: T + 1].copy(), "TEST")

        full_val = full_row["ema_20"].iloc[0]
        partial_val = result_partial.iloc[-1]["ema_20"]
        assert abs(full_val - partial_val) < 1e-6, (
            f"Lookahead detected in ema_20: full={full_val:.6f}, partial={partial_val:.6f}"
        )

    def test_warmup_rows_dropped(self):
        """Output must have fewer rows than input due to warmup period removal."""
        df = _make_ohlcv(250)
        result = calculate_features(df, "AAPL")
        assert len(result) < len(df), (
            f"Expected warmup rows to be dropped: input={len(df)}, output={len(result)}"
        )

    def test_zero_nan_in_output(self):
        """No NaN values must remain in any feature column after warmup rows are dropped."""
        df = _make_ohlcv(250)
        result = calculate_features(df, "AAPL")
        nan_counts = result.isnull().sum()
        cols_with_nan = nan_counts[nan_counts > 0]
        assert cols_with_nan.empty, f"NaN values remain in columns: {cols_with_nan.to_dict()}"

    def test_vol_ratio_20_correct_for_known_row(self):
        """vol_ratio_20 at last row = volume / mean(last 20 volumes)."""
        df = _make_ohlcv(250)

        # Override the last 20 volumes with controlled values
        df.iloc[-20:-1, df.columns.get_loc("volume")] = 1_000.0
        df.iloc[-1, df.columns.get_loc("volume")] = 2_000.0

        result = calculate_features(df.copy(), "TEST")

        expected_mean = (19 * 1_000.0 + 2_000.0) / 20.0  # 1_050.0
        expected_ratio = 2_000.0 / expected_mean           # ≈ 1.9048

        actual = result.iloc[-1]["vol_ratio_20"]
        assert abs(actual - expected_ratio) < 1e-6, (
            f"vol_ratio_20 wrong: expected {expected_ratio:.6f}, got {actual:.6f}"
        )
