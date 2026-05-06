"""Tests for consensus voting mechanism."""

import time
import pytest

from decision.consensus_voting import ConsensusVoting, StrategyVote


class TestConsensusVoting:
    """Test consensus voting functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.voting = ConsensusVoting(
            min_agreement_threshold=0.6,
            veto_confidence_threshold=0.85,
            uncertainty_threshold=0.5,
        )
    
    def test_unanimous_buy(self):
        """Test unanimous BUY vote."""
        votes = [
            StrategyVote("strat1", "us", "BUY", 0.8, 85.0, time.time()),
            StrategyVote("strat2", "us", "BUY", 0.75, 80.0, time.time()),
            StrategyVote("strat3", "us", "BUY", 0.7, 75.0, time.time()),
        ]
        
        result = self.voting.vote(votes)
        
        assert result.final_signal == "BUY"
        assert result.agreement_score == 1.0
        assert not result.dissent_detected
        assert not result.uncertainty_flag
    
    def test_majority_with_dissent(self):
        """Test majority vote with dissent."""
        votes = [
            StrategyVote("strat1", "us", "BUY", 0.8, 85.0, time.time()),
            StrategyVote("strat2", "us", "BUY", 0.75, 80.0, time.time()),
            StrategyVote("strat3", "us", "SELL", 0.7, 75.0, time.time()),
            StrategyVote("strat4", "us", "BUY", 0.65, 70.0, time.time()),
        ]
        
        result = self.voting.vote(votes)
        
        assert result.final_signal == "BUY"
        assert result.agreement_score == 0.75  # 3 out of 4
        assert not result.dissent_detected  # 75% > 60% threshold
    
    def test_veto_power(self):
        """Test veto power from high-confidence minority."""
        votes = [
            StrategyVote("strat1", "us", "BUY", 0.6, 70.0, time.time()),
            StrategyVote("strat2", "us", "BUY", 0.65, 72.0, time.time()),
            StrategyVote("strat3", "us", "SELL", 0.9, 90.0, time.time()),  # Veto
        ]
        
        result = self.voting.vote(votes)
        
        # High confidence SELL should veto majority BUY
        assert result.final_signal == "SELL"
        assert "veto" in result.reasoning.lower()
    
    def test_all_hold(self):
        """Test all strategies recommend HOLD."""
        votes = [
            StrategyVote("strat1", "us", "HOLD", 0.8, 85.0, time.time()),
            StrategyVote("strat2", "us", "HOLD", 0.75, 80.0, time.time()),
            StrategyVote("strat3", "us", "HOLD", 0.7, 75.0, time.time()),
        ]
        
        result = self.voting.vote(votes)
        
        assert result.final_signal == "HOLD"
        assert result.agreement_score == 1.0
        assert not result.uncertainty_flag
    
    def test_high_uncertainty(self):
        """Test high uncertainty with low confidence."""
        votes = [
            StrategyVote("strat1", "us", "BUY", 0.4, 60.0, time.time()),
            StrategyVote("strat2", "us", "SELL", 0.45, 62.0, time.time()),
            StrategyVote("strat3", "us", "BUY", 0.35, 58.0, time.time()),
        ]
        
        result = self.voting.vote(votes)
        
        # Should default to HOLD due to uncertainty
        assert result.final_signal == "HOLD"
        assert result.uncertainty_flag
        assert result.dissent_detected
    
    def test_no_votes(self):
        """Test empty vote list."""
        result = self.voting.vote([])
        
        assert result.final_signal == "HOLD"
        assert result.participating_strategies == 0
        assert result.uncertainty_flag
    
    def test_weighted_voting(self):
        """Test confidence and health-weighted voting."""
        votes = [
            StrategyVote("strat1", "us", "BUY", 0.9, 90.0, time.time()),  # High weight
            StrategyVote("strat2", "us", "SELL", 0.5, 50.0, time.time()),  # Low weight
            StrategyVote("strat3", "us", "SELL", 0.5, 50.0, time.time()),  # Low weight
        ]
        
        result = self.voting.vote(votes)
        
        # High-quality BUY should win despite being minority
        assert result.final_signal == "BUY"
        assert result.weighted_votes["BUY"] > result.weighted_votes["SELL"]
