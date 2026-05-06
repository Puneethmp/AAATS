"""Tests for indicators/regime_detector.py."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from indicators.regime_detector import (
    RegimeDetectorConfig,
    detect,
    get_current_regime,
)


def _make_df(n: int = 5, **overrides) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    base = {
        "timestamp": dates,
        "close": np.full(n, 100.0),
        "ema_50": np.full(n, 110.0),    # EMA50 > EMA200 → uptrend
        "ema_200": np.full(n, 100.0),
        "atr_14": np.full(n, 1.0),      # 1% ATR → below 3% threshold
        "adx_14": np.full(n, 30.0),     # ADX=30 → trending
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestDetect:
    def test_bull_trend_classification(self):
        df = _make_df()  # EMA50=110 > EMA200=100, ATR=1% < 3%, ADX=30
        result = detect(df)
        assert (result["regime"] == "BULL_TREND").all()
        assert (result["regime_score"] == 1.0).all()

    def test_bear_trend_classification(self):
        df = _make_df(ema_50=np.full(5, 90.0), ema_200=np.full(5, 100.0))
        result = detect(df)
        assert (result["regime"] == "BEAR_TREND").all()
        assert (result["regime_score"] == -1.0).all()

    def test_range_bound_classification(self):
        # EMA50 ≈ EMA200 (within 1%) AND ADX < 20
        df = _make_df(
            ema_50=np.full(5, 100.5),   # 0.5% spread → within ema_pct_band
            ema_200=np.full(5, 100.0),
            adx_14=np.full(5, 15.0),   # ADX < 20 → ranging
        )
        result = detect(df)
        assert (result["regime"] == "RANGE_BOUND").all()
        assert (result["regime_score"] == 0.0).all()

    def test_high_volatility_atr_gate(self):
        # ATR/close > 3% → HIGH_VOLATILITY overrides trend
        df = _make_df(atr_14=np.full(5, 4.0))  # 4/100 = 4% > 3%
        result = detect(df)
        assert (result["regime"] == "HIGH_VOLATILITY").all()
        assert result["regime_score"].isna().all()

    def test_high_volatility_vix_gate(self):
        # vix column present and >= 20 → HIGH_VOLATILITY
        df = _make_df()
        df["vix"] = 22.0
        result = detect(df)
        assert (result["regime"] == "HIGH_VOLATILITY").all()

    def test_vix_below_threshold_allows_bull(self):
        df = _make_df()
        df["vix"] = 15.0  # < 20 → VIX gate does not fire
        result = detect(df)
        assert (result["regime"] == "BULL_TREND").all()

    def test_nan_ema_returns_unknown(self):
        df = _make_df(ema_50=np.full(5, float("nan")))
        result = detect(df)
        assert (result["regime"] == "UNKNOWN").all()

    def test_missing_required_column_raises(self):
        df = _make_df().drop(columns=["ema_50"])
        with pytest.raises(ValueError, match="missing required columns"):
            detect(df)

    def test_adx_optional_does_not_raise(self):
        df = _make_df().drop(columns=["adx_14"])
        result = detect(df)  # Should not raise
        assert "regime" in result.columns

    def test_output_length_matches_input(self):
        df = _make_df(20)
        result = detect(df)
        assert len(result) == 20

    def test_regime_score_bull_is_positive(self):
        result = detect(_make_df())
        assert (result["regime_score"] > 0).all()

    def test_regime_score_bear_is_negative(self):
        df = _make_df(ema_50=np.full(5, 90.0), ema_200=np.full(5, 100.0))
        result = detect(df)
        assert (result["regime_score"] < 0).all()

    def test_custom_atr_threshold(self):
        config = RegimeDetectorConfig(atr_pct_high_vol=0.05)  # 5% threshold
        df = _make_df(atr_14=np.full(5, 4.0))  # 4% < 5% → not HIGH_VOL
        result = detect(df, config=config)
        assert (result["regime"] == "BULL_TREND").all()


class TestGetCurrentRegime:
    def test_returns_last_bar_regime(self):
        df = _make_df(5)
        regime = get_current_regime(df)
        assert regime == "BULL_TREND"

    def test_empty_df_returns_unknown(self):
        df = pd.DataFrame(columns=["ema_50", "ema_200", "atr_14", "close"])
        regime = get_current_regime(df)
        assert regime == "UNKNOWN"
