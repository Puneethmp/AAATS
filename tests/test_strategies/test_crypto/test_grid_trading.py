"""Tests for strategies/crypto/grid_trading.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.crypto.grid_trading import (
    GridConfig,
    GridState,
    build_grid,
    compute_position_size,
    generate_signals,
)


def _make_df(highs: list[float], lows: list[float]) -> pd.DataFrame:
    n = len(highs)
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({
        "timestamp": dates,
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
    })


class TestBuildGrid:
    def test_correct_number_of_levels(self):
        grid = build_grid(10000.0, GridConfig(n_levels=5))
        assert len(grid.buy_levels) == 5
        assert len(grid.take_profit_levels) == 5

    def test_buy_levels_descend(self):
        grid = build_grid(10000.0, GridConfig(n_levels=3, grid_spacing_pct=0.02))
        for i in range(len(grid.buy_levels) - 1):
            assert grid.buy_levels[i] > grid.buy_levels[i + 1]

    def test_take_profit_above_buy(self):
        grid = build_grid(10000.0, GridConfig(profit_pct=0.015))
        for buy, tp in zip(grid.buy_levels, grid.take_profit_levels):
            assert tp > buy

    def test_stop_loss_below_bottom_grid(self):
        grid = build_grid(10000.0, GridConfig(n_levels=3, stop_loss_pct=0.10))
        assert grid.stop_loss_price < grid.buy_levels[-1]

    def test_invalid_reference_price_raises(self):
        with pytest.raises(ValueError):
            build_grid(0.0)

    def test_reference_price_stored(self):
        grid = build_grid(50000.0)
        assert grid.reference_price == 50000.0


class TestGenerateSignals:
    def _grid(self) -> GridState:
        # Reference 10000, 5 levels at 2% spacing
        return build_grid(10000.0, GridConfig(n_levels=3, grid_spacing_pct=0.02, profit_pct=0.015, stop_loss_pct=0.10))

    def test_hold_when_price_stable(self):
        # Price stays above all buy levels and below all take-profit levels.
        # Grid ref=10000, 3 levels at 2%: buy=[9800,9600,9400], TP=[9947,9744,9541]
        # Use high=9530 (< 9541 = lowest TP) and low=9960 (> 9800 = highest buy)
        df = _make_df([9530.0] * 3, [9960.0] * 3)
        result = generate_signals(df, self._grid())
        assert (result["signal"] == "HOLD").all()

    def test_buy_when_low_hits_level(self):
        grid = self._grid()
        # buy_levels[0] = 9800; set high below all TPs (lowest TP=9541)
        first_buy = grid.buy_levels[0]  # 9800
        df = _make_df([9530.0], [first_buy - 10])  # low=9790 < 9800 → BUY; high=9530 < 9541
        result = generate_signals(df, grid)
        assert result["signal"].iloc[0] == "BUY"

    def test_take_profit_when_high_hits_tp(self):
        grid = self._grid()
        first_tp = grid.take_profit_levels[0]
        df = _make_df([first_tp + 10], [first_tp - 50])
        result = generate_signals(df, grid)
        assert result["signal"].iloc[0] == "TAKE_PROFIT"

    def test_stop_loss_priority(self):
        grid = self._grid()
        # Low breaches stop AND would hit take profit — stop wins
        stop = grid.stop_loss_price
        tp = grid.take_profit_levels[0]
        df = _make_df([tp + 10], [stop - 10])
        result = generate_signals(df, grid)
        assert result["signal"].iloc[0] == "STOP_LOSS"

    def test_missing_column_raises(self):
        grid = self._grid()
        df = _make_df([100.0], [90.0]).drop(columns=["low"])
        with pytest.raises(ValueError, match="missing columns"):
            generate_signals(df, grid)

    def test_output_length_matches_input(self):
        grid = self._grid()
        df = _make_df([9950.0] * 10, [9940.0] * 10)
        result = generate_signals(df, grid)
        assert len(result) == 10


class TestComputePositionSize:
    def test_returns_correct_amount(self):
        config = GridConfig(capital_per_level=0.10)
        size = compute_position_size(10_000, config)
        assert size == pytest.approx(1000.0)

    def test_uses_default_config(self):
        size = compute_position_size(10_000)
        assert size > 0
