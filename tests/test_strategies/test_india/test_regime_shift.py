"""Tests for strategies/india/regime_shift.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.india.regime_shift import (
    RegimeConfig,
    detect_regime,
    scale_position,
)


def _make_df(n: int = 3, **overrides) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    base = {
        "timestamp": dates,
        "close": np.full(n, 100.0),
        "ema_50": np.full(n, 110.0),   # EMA50 > EMA200 → uptrend
        "ema_200": np.full(n, 100.0),
        "india_vix": np.full(n, 12.0), # low VIX
        "adx_14": np.full(n, 30.0),    # strong trend
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestDetectRegime:
    def test_bull_trend(self):
        df = _make_df()  # EMA50 > EMA200, VIX=12, ADX=30
        result = detect_regime(df)
        assert (result["regime"] == "BULL_TREND").all()
        assert (result["position_scale"] == 1.0).all()

    def test_high_volatility_overrides_trend(self):
        df = _make_df(india_vix=np.full(3, 25.0))
        result = detect_regime(df)
        assert (result["regime"] == "HIGH_VOLATILITY").all()
        assert (result["position_scale"] == 0.0).all()

    def test_bear_trend(self):
        df = _make_df(ema_50=np.full(3, 90.0), ema_200=np.full(3, 100.0))
        result = detect_regime(df)
        assert (result["regime"] == "BEAR_TREND").all()
        assert (result["position_scale"] == 0.0).all()

    def test_range_bound(self):
        # EMA50 ≈ EMA200 (within 1%) and ADX < 20
        df = _make_df(
            ema_50=np.full(3, 100.5),   # 0.5% above EMA200=100 → within 1%
            ema_200=np.full(3, 100.0),
            adx_14=np.full(3, 15.0),    # < 20 → not trending
        )
        result = detect_regime(df)
        assert (result["regime"] == "RANGE_BOUND").all()
        assert (result["position_scale"] == 0.5).all()

    def test_missing_column_raises(self):
        df = _make_df().drop(columns=["adx_14"])
        with pytest.raises(ValueError, match="missing columns"):
            detect_regime(df)


class TestScalePosition:
    def test_bull_full_scale(self):
        assert scale_position(100, "BULL_TREND") == 100

    def test_range_half_scale(self):
        assert scale_position(100, "RANGE_BOUND") == 50

    def test_high_vol_zero_scale(self):
        assert scale_position(100, "HIGH_VOLATILITY") == 0

    def test_bear_zero_scale(self):
        assert scale_position(100, "BEAR_TREND") == 0

    def test_unknown_partial_scale(self):
        assert scale_position(100, "UNKNOWN") == 25
