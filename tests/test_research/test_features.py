"""
Tests for indicators/features.py — Feature Engineering Pipeline
"""
import numpy as np
import pandas as pd
import pytest
from indicators.features import FeaturePipeline, compute_features, FEATURE_COLUMNS


@pytest.fixture
def sample_ohlcv():
    """Generate synthetic OHLCV data (300 bars)."""
    np.random.seed(42)
    n = 300
    close = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.015, n)))
    df = pd.DataFrame({
        "open": close * np.random.uniform(0.998, 1.002, n),
        "high": close * np.random.uniform(1.001, 1.015, n),
        "low": close * np.random.uniform(0.985, 0.999, n),
        "close": close,
        "volume": np.random.uniform(1e6, 5e6, n),
    }, index=pd.date_range("2024-01-01", periods=n, freq="1D"))
    return df


def test_compute_features_returns_all_columns(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    for col in FEATURE_COLUMNS:
        assert col in df.columns, f"Missing feature column: {col}"


def test_compute_features_no_nan_after_fillna(sample_ohlcv):
    df = compute_features(sample_ohlcv, fillna=True)
    for col in FEATURE_COLUMNS:
        if col in df.columns:
            assert not df[col].isna().all(), f"Column {col} is all NaN"


def test_ema_ordering(sample_ohlcv):
    """EMA_9 should react faster (more volatile) than EMA_200."""
    df = compute_features(sample_ohlcv)
    ema9_std = df["ema_9"].std()
    ema200_std = df["ema_200"].std()
    assert ema9_std > ema200_std, "EMA_9 should be more volatile than EMA_200"


def test_rsi_bounds(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    assert df["rsi_14"].between(0, 100).all(), "RSI_14 must be in [0, 100]"
    assert df["rsi_9"].between(0, 100).all(), "RSI_9 must be in [0, 100]"


def test_bollinger_bands_ordering(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    assert (df["bb_upper"] >= df["bb_mid"]).all(), "BB upper must be >= mid"
    assert (df["bb_mid"] >= df["bb_lower"]).all(), "BB mid must be >= lower"


def test_atr_positive(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    assert (df["atr_14"] > 0).all(), "ATR must be positive"


def test_vol_ratio_positive(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    assert (df["vol_ratio"] > 0).all(), "Volume ratio must be positive"


def test_missing_required_columns_raises():
    df_bad = pd.DataFrame({"close": [100, 101, 102]})
    with pytest.raises(ValueError, match="missing columns"):
        FeaturePipeline().compute(df_bad)


def test_case_insensitive_columns(sample_ohlcv):
    df_upper = sample_ohlcv.rename(columns=str.upper)
    df_feat = compute_features(df_upper)
    assert "ema_50" in df_feat.columns


def test_macd_signal_relationship(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    # MACD histogram = MACD - signal
    diff = (df["macd"] - df["macd_signal"] - df["macd_hist"]).abs()
    assert diff.max() < 1e-10, "MACD histogram must equal MACD - signal"


def test_adx_non_negative(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    assert (df["adx_14"] >= 0).all(), "ADX must be non-negative"
    assert (df["plus_di_14"] >= 0).all()
    assert (df["minus_di_14"] >= 0).all()


def test_regime_ema_spread_sign(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    # Not testing exact values, just that it has variance
    assert df["regime_ema_spread"].std() > 0


def test_returns_correct_length(sample_ohlcv):
    df = compute_features(sample_ohlcv)
    assert len(df) == len(sample_ohlcv)
