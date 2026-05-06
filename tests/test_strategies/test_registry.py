"""Tests for strategies/registry.py."""

from __future__ import annotations

import pytest

from strategies.registry import get_strategy, list_strategies


class TestRegistry:
    def test_us_momentum_registered(self):
        fn = get_strategy("us", "momentum")
        assert callable(fn)

    def test_us_mean_reversion_registered(self):
        fn = get_strategy("us", "mean_reversion")
        assert callable(fn)

    def test_india_momentum_registered(self):
        fn = get_strategy("india", "momentum")
        assert callable(fn)

    def test_india_regime_shift_registered(self):
        fn = get_strategy("india", "regime_shift")
        assert callable(fn)

    def test_crypto_grid_trading_registered(self):
        fn = get_strategy("crypto", "grid_trading")
        assert callable(fn)

    def test_unknown_strategy_raises_key_error(self):
        with pytest.raises(KeyError, match="No strategy registered"):
            get_strategy("us", "unknown_strategy_xyz")

    def test_list_strategies_returns_all_five(self):
        strategies = list_strategies()
        assert len(strategies) >= 5
        markets = {s["market"] for s in strategies}
        assert "us" in markets
        assert "india" in markets
        assert "crypto" in markets

    def test_case_insensitive_lookup(self):
        fn1 = get_strategy("US", "MOMENTUM")
        fn2 = get_strategy("us", "momentum")
        assert fn1 is fn2
