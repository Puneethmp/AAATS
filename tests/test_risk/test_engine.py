"""Tests for risk/engine.py — all kill switches verified."""

from __future__ import annotations

import pytest

from risk.engine import (
    MARKET_DRAWDOWN_HALT,
    PER_TRADE_MAX_LOSS,
    PORTFOLIO_DRAWDOWN_HALT,
    RiskEngine,
)


class TestUpdatePortfolio:
    def test_allow_when_within_limits(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.update_portfolio(90_000)
        assert decision.action == "ALLOW"

    def test_halt_all_at_20pct_drawdown(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.update_portfolio(79_999)
        assert decision.action == "HALT_ALL"
        assert engine.is_all_halted()

    def test_exactly_at_threshold_triggers_halt(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.update_portfolio(80_000)
        assert decision.action == "HALT_ALL"

    def test_peak_tracks_new_highs(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_portfolio(120_000)
        decision = engine.update_portfolio(98_000)   # -18.3% from 120k → ok
        assert decision.action == "ALLOW"

    def test_portfolio_drawdown_method(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_portfolio(90_000)
        assert engine.portfolio_drawdown() == pytest.approx(-0.10)


class TestUpdateMarket:
    def test_allow_within_market_limit(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_market("us", 50_000)
        decision = engine.update_market("us", 44_000)  # -12% → ok
        assert decision.action == "ALLOW"

    def test_halt_market_at_15pct_drawdown(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_market("us", 50_000)
        decision = engine.update_market("us", 42_499)  # > -15% → halt
        assert decision.action == "HALT_MARKET"
        assert engine.is_market_halted("us")

    def test_halt_market_does_not_halt_others(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_market("us", 50_000)
        engine.update_market("india", 50_000)
        engine.update_market("us", 40_000)  # us halted

        assert engine.is_market_halted("us")
        assert not engine.is_market_halted("india")

    def test_market_drawdown_method(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_market("crypto", 10_000)
        engine.update_market("crypto", 9_000)
        assert engine.market_drawdown("crypto") == pytest.approx(-0.10)


class TestCheckNewOrder:
    def test_allow_valid_order(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.check_new_order("us", entry_price=100, shares=5, capital=50_000)
        assert decision.action == "ALLOW"

    def test_reduce_order_exceeding_2pct(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.check_new_order("us", entry_price=100, shares=200, capital=50_000)
        assert decision.action == "REDUCE"
        assert decision.allowed_fraction < 1.0

    def test_blocked_when_all_halted(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_portfolio(79_000)
        decision = engine.check_new_order("us", 100, 5, 50_000)
        assert decision.action == "HALT_ALL"

    def test_blocked_when_market_halted(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_market("india", 50_000)
        engine.update_market("india", 40_000)  # -20% → halted
        decision = engine.check_new_order("india", 100, 5, 40_000)
        assert decision.action == "HALT_MARKET"


class TestCheckOpenPosition:
    def test_allow_profitable_position(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.check_open_position("us", entry_price=100, current_price=105)
        assert decision.action == "ALLOW"

    def test_allow_small_loss(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.check_open_position("us", entry_price=100, current_price=99)
        assert decision.action == "ALLOW"

    def test_close_at_2pct_loss(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.check_open_position("us", entry_price=100, current_price=98)
        assert decision.action == "CLOSE_POSITION"

    def test_close_beyond_2pct_loss(self):
        engine = RiskEngine(initial_portfolio=100_000)
        decision = engine.check_open_position("us", entry_price=100, current_price=95)
        assert decision.action == "CLOSE_POSITION"


class TestResetMethods:
    def test_reset_market_clears_halt(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_market("us", 50_000)
        engine.update_market("us", 40_000)
        assert engine.is_market_halted("us")
        engine.reset_market("us")
        assert not engine.is_market_halted("us")

    def test_reset_all_clears_everything(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.update_portfolio(79_000)
        assert engine.is_all_halted()
        engine.reset_all()
        assert not engine.is_all_halted()

    def test_reset_market_no_error_if_not_halted(self):
        engine = RiskEngine(initial_portfolio=100_000)
        engine.reset_market("us")
