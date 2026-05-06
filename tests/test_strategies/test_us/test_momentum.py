"""
Tests for strategies/us/momentum.py.
All tests use synthetic DataFrames — no live data or external calls.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.us.momentum import (
    MomentumConfig,
    compute_position_size,
    generate_signals,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_df(n: int = 10, **overrides) -> pd.DataFrame:
    """Build a minimal feature DataFrame with all required columns."""
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    base = {
        "timestamp": dates,
        "open": np.linspace(100, 110, n),
        "high": np.linspace(105, 115, n),
        "low": np.linspace(95, 105, n),
        "close": np.linspace(102, 112, n),        # close > ema_50 always
        "ema_50": np.linspace(100, 110, n),    # EMA50 < close → price above trend
        "ema_200": np.linspace(90, 100, n),    # EMA200 < EMA50 → uptrend
        "return_5d": [0.02] * n,               # default: positive momentum
        "atr_14": [2.0] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base)


# ── generate_signals tests ────────────────────────────────────────────────────

class TestGenerateSignals:
    def test_buy_when_all_conditions_met(self):
        df = _make_df(5)
        result = generate_signals(df)
        assert (result["signal"] == "BUY").all()

    def test_sell_on_death_cross(self):
        # EMA50 < EMA200 → death cross
        df = _make_df(5, ema_50=np.full(5, 90.0), ema_200=np.full(5, 100.0))
        result = generate_signals(df)
        assert (result["signal"] == "SELL").all()

    def test_hold_when_momentum_negative(self):
        # EMA50 > EMA200 but return_5d < 0
        df = _make_df(5, return_5d=[-0.01] * 5)
        result = generate_signals(df)
        # No death cross → not SELL; entry condition fails → should be HOLD
        assert (result["signal"] == "HOLD").all()

    def test_hold_when_price_below_ema50(self):
        close = np.linspace(85, 95, 5)   # below EMA50
        ema_50 = np.full(5, 100.0)
        ema_200 = np.full(5, 90.0)       # EMA50 > EMA200 → uptrend
        df = _make_df(5, close=close, ema_50=ema_50, ema_200=ema_200)
        result = generate_signals(df)
        assert (result["signal"] == "HOLD").all()

    def test_sell_overrides_entry_on_same_bar(self):
        # Construct a bar where entry conditions are met but EMA50 < EMA200
        df = _make_df(
            1,
            ema_50=np.array([95.0]),
            ema_200=np.array([100.0]),  # death cross → SELL
            return_5d=[0.02],
            close=np.array([96.0]),
        )
        result = generate_signals(df)
        assert result["signal"].iloc[0] == "SELL"

    def test_returns_signal_strength_column(self):
        df = _make_df(5)
        result = generate_signals(df)
        assert "signal_strength" in result.columns
        assert result["signal_strength"].between(0, 1).all()

    def test_signal_strength_full_when_all_conditions_met(self):
        df = _make_df(5)
        result = generate_signals(df)
        assert (result["signal_strength"] == 1.0).all()

    def test_stop_loss_column_present(self):
        df = _make_df(5)
        result = generate_signals(df)
        assert "stop_loss" in result.columns

    def test_stop_loss_below_close(self):
        df = _make_df(5)
        result = generate_signals(df)
        assert (result["stop_loss"] < result["close"]).all()

    def test_missing_column_raises(self):
        df = _make_df(5).drop(columns=["ema_200"])
        with pytest.raises(ValueError, match="missing columns"):
            generate_signals(df)

    def test_output_has_same_length_as_input(self):
        df = _make_df(20)
        result = generate_signals(df)
        assert len(result) == 20

    def test_custom_atr_multiplier(self):
        config = MomentumConfig(atr_stop_multiplier=3.0)
        df = _make_df(5, atr_14=np.full(5, 2.0))
        result = generate_signals(df, config=config)
        # stop_loss = close - 3.0 * 2.0 = close - 6.0
        expected_stop = result["close"] - 6.0
        pd.testing.assert_series_equal(result["stop_loss"], expected_stop, check_names=False)


# ── compute_position_size tests ───────────────────────────────────────────────

class TestComputePositionSize:
    def test_basic_position_size(self):
        # 10000 capital, 1.5% risk = 150 risk budget
        # entry=100, stop=90 → risk/share=10 → 15 shares
        shares = compute_position_size(10_000, 100.0, 90.0)
        assert shares == 15

    def test_returns_at_least_one_share(self):
        # Very small risk budget still returns 1
        shares = compute_position_size(100, 100.0, 99.9)
        assert shares >= 1

    def test_invalid_stop_loss_returns_zero(self):
        # stop >= entry → no position
        shares = compute_position_size(10_000, 100.0, 100.0)
        assert shares == 0

    def test_stop_above_entry_returns_zero(self):
        shares = compute_position_size(10_000, 100.0, 110.0)
        assert shares == 0

    def test_custom_risk_config(self):
        config = MomentumConfig(max_risk_per_trade=0.01)
        # 10000 * 1% = 100 risk; entry=100, stop=90 → risk/share=10 → 10 shares
        shares = compute_position_size(10_000, 100.0, 90.0, config=config)
        assert shares == 10

    def test_larger_capital_more_shares(self):
        shares_small = compute_position_size(10_000, 100.0, 90.0)
        shares_large = compute_position_size(100_000, 100.0, 90.0)
        assert shares_large > shares_small
