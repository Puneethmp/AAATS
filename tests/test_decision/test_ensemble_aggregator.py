"""Tests for ensemble signal aggregation."""

import time
import pytest

from decision.ensemble_aggregator import EnsembleAggregator, StrategySignal


class TestEnsembleAggregator:
    """Test ensemble aggregation functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.aggregator = EnsembleAggregator(
            min_strategies=3,
            performance_weight=0.6,
            health_weight=0.4,
            temporal_window=5,
        )
    
    def test_basic_aggregation(self):
        """Test basic signal aggregation."""
        signals = [
            StrategySignal("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, time.time()),
            StrategySignal("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, time.time()),
            StrategySignal("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, time.time()),
        ]
        
        result = self.aggregator.aggregate(signals)
        
        assert result.final_signal == "BUY"
        assert result.contributing_strategies == 3
        assert result.ensemble_confidence > 0.7
    
    def test_insufficient_strategies(self):
        """Test with insufficient strategies."""
        signals = [
            StrategySignal("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, time.time()),
            StrategySignal("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, time.time()),
        ]
        
        result = self.aggregator.aggregate(signals)
        
        assert result.final_signal == "HOLD"
        assert "Insufficient" in result.reasoning
    
    def test_performance_weighting(self):
        """Test performance-based weighting."""
        signals = [
            StrategySignal("high_perf", "us", "BUY", 0.7, 1.0, 80.0, 2.5, time.time()),
            StrategySignal("low_perf1", "us", "SELL", 0.7, 1.0, 80.0, 0.5, time.time()),
            StrategySignal("low_perf2", "us", "SELL", 0.7, 1.0, 80.0, 0.5, time.time()),
        ]
        
        result = self.aggregator.aggregate(signals)
        
        # High-performance strategy should have more weight
        assert result.strategy_weights["high_perf"] > result.strategy_weights["low_perf1"]
    
    def test_temporal_consistency(self):
        """Test temporal consistency tracking."""
        # First round of signals
        signals1 = [
            StrategySignal("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, time.time()),
            StrategySignal("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, time.time()),
            StrategySignal("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, time.time()),
        ]
        
        result1 = self.aggregator.aggregate(signals1)
        assert result1.temporal_consistency == 1.0  # No history yet
        
        # Second round - same signals (consistent)
        signals2 = [
            StrategySignal("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, time.time()),
            StrategySignal("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, time.time()),
            StrategySignal("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, time.time()),
        ]
        
        result2 = self.aggregator.aggregate(signals2)
        assert result2.temporal_consistency == 1.0  # All consistent
        
        # Third round - one strategy changes (inconsistent)
        signals3 = [
            StrategySignal("strat1", "us", "SELL", 0.8, 1.5, 85.0, 1.8, time.time()),
            StrategySignal("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, time.time()),
            StrategySignal("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, time.time()),
        ]
        
        result3 = self.aggregator.aggregate(signals3)
        assert result3.temporal_consistency < 1.0  # strat1 changed
    
    def test_mixed_signals(self):
        """Test aggregation with mixed signals."""
        signals = [
            StrategySignal("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, time.time()),
            StrategySignal("strat2", "us", "SELL", 0.75, 1.3, 80.0, 1.6, time.time()),
            StrategySignal("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, time.time()),
            StrategySignal("strat4", "us", "HOLD", 0.6, 1.0, 70.0, 1.2, time.time()),
        ]
        
        result = self.aggregator.aggregate(signals)
        
        # Should pick signal with highest weighted score
        assert result.final_signal in ["BUY", "SELL", "HOLD"]
        assert 0.0 <= result.ensemble_confidence <= 1.0
    
    def test_reset_history(self):
        """Test history reset functionality."""
        signals = [
            StrategySignal("strat1", "us", "BUY", 0.8, 1.5, 85.0, 1.8, time.time()),
            StrategySignal("strat2", "us", "BUY", 0.75, 1.3, 80.0, 1.6, time.time()),
            StrategySignal("strat3", "us", "BUY", 0.7, 1.2, 75.0, 1.4, time.time()),
        ]
        
        self.aggregator.aggregate(signals)
        assert len(self.aggregator.signal_history) > 0
        
        self.aggregator.reset_history()
        assert len(self.aggregator.signal_history) == 0
