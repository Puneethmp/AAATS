"""Tests for strategies/india/momentum.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.india.momentum import (
    IndiaMomentumConfig,
    compute_position_size,
    generate_signals,
)


def _make_df(n: int = 5, **overrides) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    base = {
        "timestamp": dates,
        "close": np.linspace(102, 112, n),     # close > ema_50
        "ema_50": np.linspace(100, 110, n),    # EMA50 < close and > EMA200
        "ema_200": np.linspace(90, 100, n),    # EMA200 < EMA50 → uptrend
        "returns_5d": np.full(n, 0.02),
        "atr_14": np.full(n, 2.0),
        "india_vix": np.full(n, 15.0),         # below threshold → OK
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestGenerateSignals:
    def test_buy_when_all_conditions_met(self):
        df = _make_df(5)
        result = generate_signals(df)
        assert (result["signal"] == "BUY").all()

    def test_vix_gate_blocks_buy(self):
        df = _make_df(5, india_vix=np.full(5, 22.0))  # VIX >= 20 → no BUY
        result = generate_signals(df)
        assert (result["signal"] == "SELL").all()  # vix spike triggers exit

    def test_vix_blocked_column_set(self):
        # VIX blocks what would otherwise be a BUY
        df = _make_df(5, india_vix=np.full(5, 21.0))
        result = generate_signals(df)
        assert result["vix_blocked"].all()

    def test_death_cross_triggers_sell(self):
        df = _make_df(5, ema_50=np.full(5, 90.0), ema_200=np.full(5, 100.0))
        result = generate_signals(df)
        assert (result["signal"] == "SELL").all()

    def test_negative_momentum_gives_hold(self):
        df = _make_df(5, returns_5d=np.full(5, -0.01))
        result = generate_signals(df)
        # No death cross → not SELL; entry fails → HOLD
        assert (result["signal"] == "HOLD").all()

    def test_missing_column_raises(self):
        df = _make_df(5).drop(columns=["india_vix"])
        with pytest.raises(ValueError, match="missing columns"):
            generate_signals(df)

    def test_custom_vix_threshold(self):
        config = IndiaMomentumConfig(vix_threshold=25.0)
        df = _make_df(5, india_vix=np.full(5, 22.0))  # 22 < 25 → VIX ok
        result = generate_signals(df, config=config)
        assert (result["signal"] == "BUY").all()


class TestComputePositionSize:
    def test_basic(self):
        # 10000 * 1.5% = 150; entry=100, stop=90 → 15 shares
        assert compute_position_size(10_000, 100.0, 90.0) == 15

    def test_invalid_stop_returns_zero(self):
        assert compute_position_size(10_000, 100.0, 100.0) == 0

    def test_minimum_one_share(self):
        assert compute_position_size(100, 1000.0, 999.0) >= 1
