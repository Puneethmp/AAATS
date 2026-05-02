"""Tests for meta-strategy coordinator."""

import time
import pytest

from decision.meta_coordinator import (
    MetaCoordinator,
    StrategyInput,
    MarketContext,
)


class TestMetaCoordinator:
    """Test meta-coordinator functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.coordinator = MetaCoordinator(
            min_strategies=3,
            use_hybrid_mode=True,
        )
    
    def test_basic_coordination(self):
        """Test basic decision coordination."""
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
            StrategyInput("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, 0.8, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="bullish",
            regime="bull_trend",
            current_volatility=0.15,
            target_volatility=0.15,
            portfolio_risk_score=30.0,
            capital_throttle_level="none",
        )
        
        decision = self.coordinator.coordinate_decision(inputs, context)
        
        assert decision.signal == "BUY"
        assert decision.should_execute
        assert decision.participating_strategies == 3
        assert not decision.risk_override
    
    def test_insufficient_strategies(self):
        """Test with insufficient strategies."""
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="bullish",
            regime="bull_trend",
            current_volatility=0.15,
            target_volatility=0.15,
            portfolio_risk_score=30.0,
            capital_throttle_level="none",
        )
        
        decision = self.coordinator.coordinate_decision(inputs, context)
        
        assert decision.signal == "HOLD"
        assert not decision.should_execute
        assert "Insufficient" in decision.reasoning
    
    def test_risk_override_high_portfolio_risk(self):
        """Test risk override due to high portfolio risk."""
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
            StrategyInput("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, 0.8, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="bullish",
            regime="bull_trend",
            current_volatility=0.15,
            target_volatility=0.15,
            portfolio_risk_score=80.0,  # Critical risk
            capital_throttle_level="none",
        )
        
        decision = self.coordinator.coordinate_decision(inputs, context)
        
        assert decision.signal == "HOLD"
        assert decision.risk_override
        assert not decision.should_execute
    
    def test_risk_override_capital_throttle(self):
        """Test risk override due to capital throttle."""
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
            StrategyInput("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, 0.8, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="bullish",
            regime="bull_trend",
            current_volatility=0.15,
            target_volatility=0.15,
            portfolio_risk_score=30.0,
            capital_throttle_level="heavy",  # Heavy throttle
        )
        
        decision = self.coordinator.coordinate_decision(inputs, context)
        
        assert decision.signal == "HOLD"
        assert decision.risk_override
        assert not decision.should_execute
    
    def test_risk_override_extreme_volatility(self):
        """Test risk override due to extreme volatility."""
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
            StrategyInput("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, 0.8, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="bullish",
            regime="bull_trend",
            current_volatility=0.45,  # 3x target
            target_volatility=0.15,
            portfolio_risk_score=30.0,
            capital_throttle_level="none",
        )
        
        decision = self.coordinator.coordinate_decision(inputs, context)
        
        assert decision.signal == "HOLD"
        assert decision.risk_override
        assert not decision.should_execute
    
    def test_hybrid_mode_agreement(self):
        """Test hybrid mode when consensus and ensemble agree."""
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
            StrategyInput("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, 0.8, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="bullish",
            regime="bull_trend",
            current_volatility=0.15,
            target_volatility=0.15,
            portfolio_risk_score=30.0,
            capital_throttle_level="none",
        )
        
        decision = self.coordinator.coordinate_decision(inputs, context)
        
        assert decision.decision_method == "hybrid_agreement"
        assert decision.consensus_result.final_signal == decision.ensemble_result.final_signal
    
    def test_consensus_only_mode(self):
        """Test consensus-only mode (no hybrid)."""
        coordinator = MetaCoordinator(
            min_strategies=3,
            use_hybrid_mode=False,
        )
        
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
            StrategyInput("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, 0.8, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="bullish",
            regime="bull_trend",
            current_volatility=0.15,
            target_volatility=0.15,
            portfolio_risk_score=30.0,
            capital_throttle_level="none",
        )
        
        decision = coordinator.coordinate_decision(inputs, context)
        
        assert decision.decision_method == "consensus"
    
    def test_mixed_signals(self):
        """Test coordination with mixed signals."""
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "SELL", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
            StrategyInput("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, 0.8, time.time()),
            StrategyInput("strat4", "us", "HOLD", 0.6, 1.0, 70.0, 1.2, 0.75, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="neutral",
            regime="sideways",
            current_volatility=0.15,
            target_volatility=0.15,
            portfolio_risk_score=40.0,
            capital_throttle_level="none",
        )
        
        decision = self.coordinator.coordinate_decision(inputs, context)
        
        # Should make a decision despite mixed signals
        assert decision.signal in ["BUY", "SELL", "HOLD"]
        assert 0.0 <= decision.confidence <= 1.0
    
    def test_decision_summary(self):
        """Test decision summary generation."""
        inputs = [
            StrategyInput("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, 0.9, time.time()),
            StrategyInput("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, 0.85, time.time()),
            StrategyInput("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, 0.8, time.time()),
        ]
        
        context = MarketContext(
            market="us",
            trend="bullish",
            regime="bull_trend",
            current_volatility=0.15,
            target_volatility=0.15,
            portfolio_risk_score=30.0,
            capital_throttle_level="none",
        )
        
        decision = self.coordinator.coordinate_decision(inputs, context)
        summary = self.coordinator.get_decision_summary(decision)
        
        assert "Market:" in summary
        assert "Signal:" in summary
        assert "Confidence:" in summary
        assert "Execute:" in summary
