"""
Tests for strategies/us/mean_reversion.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.us.mean_reversion import (
    MeanReversionConfig,
    compute_position_size,
    generate_signals,
)


def _make_df(n: int = 5, **overrides) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    base = {
        "timestamp": dates,
        "close": np.full(n, 100.0),
        "bb_mid": np.full(n, 105.0),    # close < bb_mid
        "bb_upper": np.full(n, 110.0),
        "bb_lower": np.full(n, 100.0),  # close == bb_lower (not strictly below)
        "atr_14": np.full(n, 2.0),
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestGenerateSignals:
    def test_buy_when_price_below_lower_band(self):
        # close = 95 < bb_lower = 100 → BUY
        df = _make_df(5, close=np.full(5, 95.0), bb_lower=np.full(5, 100.0), bb_mid=np.full(5, 105.0))
        result = generate_signals(df)
        assert (result["signal"] == "BUY").all()

    def test_sell_when_price_at_midband(self):
        # close = 105 >= bb_mid = 105 → SELL
        df = _make_df(5, close=np.full(5, 105.0), bb_lower=np.full(5, 100.0), bb_mid=np.full(5, 105.0))
        result = generate_signals(df)
        assert (result["signal"] == "SELL").all()

    def test_sell_when_price_above_midband(self):
        df = _make_df(5, close=np.full(5, 108.0), bb_lower=np.full(5, 100.0), bb_mid=np.full(5, 105.0))
        result = generate_signals(df)
        assert (result["signal"] == "SELL").all()

    def test_hold_between_bands(self):
        # close = 103 — above bb_lower=100 (not oversold) and below bb_mid=105
        df = _make_df(5, close=np.full(5, 103.0))
        result = generate_signals(df)
        assert (result["signal"] == "HOLD").all()

    def test_sell_overrides_buy_on_same_bar(self):
        # close < bb_lower AND >= bb_mid is logically impossible, but
        # test that reverted takes priority if both flags are somehow set
        # (close == 105 which is >= bb_mid=105 and we set bb_lower=106 so close < bb_lower)
        df = _make_df(1, close=np.array([105.0]), bb_lower=np.array([106.0]), bb_mid=np.array([105.0]))
        result = generate_signals(df)
        assert result["signal"].iloc[0] == "SELL"

    def test_stop_loss_below_close(self):
        df = _make_df(5, close=np.full(5, 95.0), bb_lower=np.full(5, 100.0))
        result = generate_signals(df)
        assert (result["stop_loss"] < result["close"]).all()

    def test_z_score_proxy_negative_when_oversold(self):
        # close well below midband → z_score_proxy negative
        df = _make_df(5, close=np.full(5, 90.0), bb_lower=np.full(5, 100.0),
                      bb_mid=np.full(5, 105.0), bb_upper=np.full(5, 110.0))
        result = generate_signals(df)
        assert (result["z_score_proxy"] < 0).all()

    def test_missing_column_raises(self):
        df = _make_df(5).drop(columns=["bb_lower"])
        with pytest.raises(ValueError, match="missing columns"):
            generate_signals(df)

    def test_output_length_matches_input(self):
        df = _make_df(15)
        result = generate_signals(df)
        assert len(result) == 15


class TestComputePositionSize:
    def test_basic_calculation(self):
        # 10000 * 1.5% = 150 risk; entry=100, stop=90 → 15 shares
        shares = compute_position_size(10_000, 100.0, 90.0)
        assert shares == 15

    def test_stop_at_or_above_entry_returns_zero(self):
        assert compute_position_size(10_000, 100.0, 100.0) == 0
        assert compute_position_size(10_000, 100.0, 110.0) == 0

    def test_minimum_one_share(self):
        # Tiny capital, still get at least 1 share
        shares = compute_position_size(100, 1000.0, 999.0)
        assert shares >= 1

    def test_custom_risk_config(self):
        config = MeanReversionConfig(max_risk_per_trade=0.01)
        # 10000 * 1% = 100; entry=100, stop=90 → 10 shares
        shares = compute_position_size(10_000, 100.0, 90.0, config=config)
        assert shares == 10
