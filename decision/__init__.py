"""
Decision layer for AAATS - Consensus & Ensemble Intelligence.

Provides sophisticated multi-strategy decision-making:
  - Consensus voting across strategies
  - Ensemble signal aggregation
  - Multi-factor confidence scoring
  - Meta-strategy coordination
  - Portfolio intelligence integration

Usage:
    from decision import MetaCoordinator, StrategyInput, MarketContext
    
    coordinator = MetaCoordinator()
    decision = coordinator.coordinate_decision(strategy_inputs, market_context)
"""

from decision.consensus_voting import (
    ConsensusVoting,
    StrategyVote,
    ConsensusResult,
)

from decision.ensemble_aggregator import (
    EnsembleAggregator,
    StrategySignal,
    EnsembleSignal,
)

from decision.confidence_scorer import (
    ConfidenceScorer,
    ConfidenceFactors,
    ConfidenceScore,
)

from decision.meta_coordinator import (
    MetaCoordinator,
    StrategyInput,
    MarketContext,
    FinalDecision,
)

__all__ = [
    # Consensus voting
    "ConsensusVoting",
    "StrategyVote",
    "ConsensusResult",
    
    # Ensemble aggregation
    "EnsembleAggregator",
    "StrategySignal",
    "EnsembleSignal",
    
    # Confidence scoring
    "ConfidenceScorer",
    "ConfidenceFactors",
    "ConfidenceScore",
    
    # Meta-coordination
    "MetaCoordinator",
    "StrategyInput",
    "MarketContext",
    "FinalDecision",
]
