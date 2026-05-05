"""
Consensus voting mechanism for multi-strategy signal aggregation.

Implements democratic voting across strategies to determine final trading decisions:
  - Majority voting with confidence weighting
  - Disagreement detection and uncertainty gating
  - Strategy credibility scoring
  - Veto power for high-confidence dissent
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from foundation.logger import get_logger

_log = get_logger("decision", "consensus_voting")


@dataclass
class StrategyVote:
    """Individual strategy vote."""
    strategy_id: str
    market: str
    signal: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0.0-1.0
    health_score: float  # 0-100 (strategy health)
    timestamp: float


@dataclass
class ConsensusResult:
    """Result of consensus voting."""
    final_signal: str  # "BUY", "SELL", "HOLD"
    consensus_confidence: float  # 0.0-1.0
    agreement_score: float  # 0.0-1.0 (how much strategies agree)
    participating_strategies: int
    vote_breakdown: Dict[str, int]  # {"BUY": 3, "SELL": 1, "HOLD": 2}
    weighted_votes: Dict[str, float]  # Confidence-weighted votes
    dissent_detected: bool
    uncertainty_flag: bool
    reasoning: str


class ConsensusVoting:
    """
    Democratic voting mechanism for multi-strategy consensus.
    
    Features:
      - Majority voting with confidence weighting
      - Health-based credibility scoring
      - Disagreement detection (>30% dissent)
      - Veto power for high-confidence minority
      - Uncertainty gating when consensus is weak
    """
    
    def __init__(
        self,
        min_agreement_threshold: float = 0.6,
        veto_confidence_threshold: float = 0.85,
        uncertainty_threshold: float = 0.5,
    ):
        """
        Initialize consensus voting engine.
        
        Args:
            min_agreement_threshold: Minimum agreement score to proceed (0.6 = 60%)
            veto_confidence_threshold: Confidence needed for veto power (0.85)
            uncertainty_threshold: Below this consensus confidence, flag uncertainty
        """
        self.min_agreement_threshold = min_agreement_threshold
        self.veto_confidence_threshold = veto_confidence_threshold
        self.uncertainty_threshold = uncertainty_threshold
        
        _log.info(
            f"Initialized consensus voting: "
            f"agreement_threshold={min_agreement_threshold:.2f}, "
            f"veto_threshold={veto_confidence_threshold:.2f}"
        )
    
    def vote(self, votes: List[StrategyVote]) -> ConsensusResult:
        """
        Aggregate strategy votes into consensus decision.
        
        Args:
            votes: List of strategy votes
        
        Returns:
            ConsensusResult with final decision and metadata
        """
        if not votes:
            return ConsensusResult(
                final_signal="HOLD",
                consensus_confidence=0.0,
                agreement_score=0.0,
                participating_strategies=0,
                vote_breakdown={},
                weighted_votes={},
                dissent_detected=False,
                uncertainty_flag=True,
                reasoning="No votes received"
            )
        
        # Filter out HOLD votes for active decision-making
        active_votes = [v for v in votes if v.signal != "HOLD"]
        
        if not active_votes:
            return ConsensusResult(
                final_signal="HOLD",
                consensus_confidence=0.8,
                agreement_score=1.0,
                participating_strategies=len(votes),
                vote_breakdown={"HOLD": len(votes)},
                weighted_votes={"HOLD": float(len(votes))},
                dissent_detected=False,
                uncertainty_flag=False,
                reasoning="All strategies recommend HOLD"
            )
        
        # Calculate vote breakdown
        vote_breakdown = self._count_votes(votes)
        
        # Calculate weighted votes (confidence × health)
        weighted_votes = self._calculate_weighted_votes(votes)
        
        # Determine majority signal
        majority_signal = max(weighted_votes.items(), key=lambda x: x[1])[0]
        
        # Calculate agreement score
        agreement_score = self._calculate_agreement(votes, majority_signal)
        
        # Calculate consensus confidence
        consensus_confidence = self._calculate_consensus_confidence(
            votes, majority_signal
        )
        
        # Check for veto power
        veto_signal = self._check_veto_power(votes, majority_signal)
        if veto_signal:
            final_signal = veto_signal
            reasoning = f"Veto power exercised: high-confidence {veto_signal} overrides majority"
        else:
            final_signal = majority_signal
            reasoning = f"Majority consensus: {majority_signal}"
        
        # Detect dissent
        dissent_detected = agreement_score < self.min_agreement_threshold
        
        # Flag uncertainty
        uncertainty_flag = consensus_confidence < self.uncertainty_threshold
        
        # Override to HOLD if uncertainty is too high (either condition alone suffices)
        if uncertainty_flag:
            final_signal = "HOLD"
            reasoning = "Consensus confidence below threshold - defaulting to HOLD"
        
        return ConsensusResult(
            final_signal=final_signal,
            consensus_confidence=consensus_confidence,
            agreement_score=agreement_score,
            participating_strategies=len(votes),
            vote_breakdown=vote_breakdown,
            weighted_votes=weighted_votes,
            dissent_detected=dissent_detected,
            uncertainty_flag=uncertainty_flag,
            reasoning=reasoning
        )
    
    def _count_votes(self, votes: List[StrategyVote]) -> Dict[str, int]:
        """Count raw votes by signal type."""
        breakdown = {"BUY": 0, "SELL": 0, "HOLD": 0}
        for vote in votes:
            breakdown[vote.signal] = breakdown.get(vote.signal, 0) + 1
        return breakdown
    
    def _calculate_weighted_votes(
        self, votes: List[StrategyVote]
    ) -> Dict[str, float]:
        """
        Calculate confidence and health-weighted votes.
        
        Weight = confidence × (health_score / 100)
        """
        weighted = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        
        for vote in votes:
            # Weight by confidence and health
            weight = vote.confidence * (vote.health_score / 100.0)
            weighted[vote.signal] += weight
        
        return weighted
    
    def _calculate_agreement(
        self, votes: List[StrategyVote], majority_signal: str
    ) -> float:
        """
        Calculate agreement score (0.0-1.0).
        
        Agreement = (votes for majority) / (total votes)
        """
        if not votes:
            return 0.0
        
        majority_count = sum(1 for v in votes if v.signal == majority_signal)
        return majority_count / len(votes)
    
    def _calculate_consensus_confidence(
        self, votes: List[StrategyVote], majority_signal: str
    ) -> float:
        """
        Calculate consensus confidence (0.0-1.0).
        
        Average confidence of strategies voting for majority signal.
        """
        majority_votes = [v for v in votes if v.signal == majority_signal]
        
        if not majority_votes:
            return 0.0
        
        # Weighted average by health score
        total_weight = sum(v.health_score for v in majority_votes)
        if total_weight == 0:
            return 0.0
        
        weighted_confidence = sum(
            v.confidence * v.health_score for v in majority_votes
        )
        
        return weighted_confidence / total_weight
    
    def _check_veto_power(
        self, votes: List[StrategyVote], majority_signal: str
    ) -> str | None:
        """
        Check if any minority vote has veto power.
        
        Veto power: High-confidence (>0.85) vote from healthy strategy (>80)
        that disagrees with majority.
        
        Returns:
            Signal to override with, or None if no veto
        """
        for vote in votes:
            if vote.signal == majority_signal:
                continue  # Not a dissenting vote
            
            # Check veto criteria
            has_high_confidence = vote.confidence >= self.veto_confidence_threshold
            has_high_health = vote.health_score >= 80.0
            
            if has_high_confidence and has_high_health:
                _log.warning(
                    f"Veto power exercised by {vote.strategy_id}: "
                    f"{vote.signal} (confidence={vote.confidence:.2f}, "
                    f"health={vote.health_score:.1f})"
                )
                return vote.signal
        
        return None
    
    def get_vote_summary(self, result: ConsensusResult) -> str:
        """Generate human-readable vote summary."""
        summary = [
            f"Consensus: {result.final_signal}",
            f"Confidence: {result.consensus_confidence:.2%}",
            f"Agreement: {result.agreement_score:.2%}",
            f"Strategies: {result.participating_strategies}",
            f"Breakdown: {result.vote_breakdown}",
        ]
        
        if result.dissent_detected:
            summary.append("⚠️ Dissent detected")
        
        if result.uncertainty_flag:
            summary.append("⚠️ High uncertainty")
        
        return " | ".join(summary)
