"""
Meta-strategy coordination layer for orchestrating ensemble intelligence.

Integrates all decision components:
  - Consensus voting
  - Ensemble aggregation
  - Confidence scoring
  - Portfolio intelligence integration
  - Final decision orchestration
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import time

from foundation.logger import get_logger
from decision.consensus_voting import ConsensusVoting, StrategyVote, ConsensusResult
from decision.ensemble_aggregator import EnsembleAggregator, StrategySignal, EnsembleSignal
from decision.confidence_scorer import ConfidenceScorer, ConfidenceScore

_log = get_logger("decision", "meta_coordinator")


@dataclass
class StrategyInput:
    """Input from a single strategy."""
    strategy_id: str
    market: str
    signal: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0.0-1.0
    strength: float  # Signal strength
    health_score: float  # 0-100
    sharpe_ratio: float
    regime_fit: float  # 0.0-1.0
    timestamp: float


@dataclass
class MarketContext:
    """Current market context for decision-making."""
    market: str
    trend: str  # "bullish", "bearish", "neutral"
    regime: str  # "bull_trend", "bear_trend", "sideways", etc.
    current_volatility: float
    target_volatility: float
    portfolio_risk_score: float  # 0-100 from risk aggregator
    capital_throttle_level: str  # "none", "light", "moderate", "heavy", "full"


@dataclass
class FinalDecision:
    """Final coordinated trading decision."""
    market: str
    signal: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0.0-1.0
    should_execute: bool
    
    # Component results
    consensus_result: ConsensusResult
    ensemble_result: EnsembleSignal
    confidence_score: ConfidenceScore
    
    # Metadata
    participating_strategies: int
    decision_method: str  # "consensus", "ensemble", "hybrid"
    risk_override: bool  # Whether risk controls overrode decision
    reasoning: str
    timestamp: float


class MetaCoordinator:
    """
    Meta-strategy coordination engine.
    
    Orchestrates all decision-making components:
      1. Collects signals from all strategies
      2. Runs consensus voting
      3. Runs ensemble aggregation
      4. Calculates confidence scores
      5. Integrates portfolio intelligence
      6. Makes final coordinated decision
    """
    
    def __init__(
        self,
        consensus_voting: Optional[ConsensusVoting] = None,
        ensemble_aggregator: Optional[EnsembleAggregator] = None,
        confidence_scorer: Optional[ConfidenceScorer] = None,
        min_strategies: int = 3,
        use_hybrid_mode: bool = True,
    ):
        """
        Initialize meta-coordinator.
        
        Args:
            consensus_voting: Consensus voting engine (creates default if None)
            ensemble_aggregator: Ensemble aggregator (creates default if None)
            confidence_scorer: Confidence scorer (creates default if None)
            min_strategies: Minimum strategies required for decision
            use_hybrid_mode: Use hybrid consensus+ensemble (True) or consensus only (False)
        """
        self.consensus_voting = consensus_voting or ConsensusVoting()
        self.ensemble_aggregator = ensemble_aggregator or EnsembleAggregator()
        self.confidence_scorer = confidence_scorer or ConfidenceScorer()
        self.min_strategies = min_strategies
        self.use_hybrid_mode = use_hybrid_mode
        
        _log.info(
            f"Initialized meta-coordinator: "
            f"min_strategies={min_strategies}, "
            f"hybrid_mode={use_hybrid_mode}"
        )
    
    def coordinate_decision(
        self,
        strategy_inputs: List[StrategyInput],
        market_context: MarketContext,
    ) -> FinalDecision:
        """
        Coordinate final trading decision from multiple strategies.
        
        Args:
            strategy_inputs: List of strategy signals
            market_context: Current market context
        
        Returns:
            FinalDecision with coordinated result
        """
        timestamp = time.time()
        
        # Validate minimum strategies
        if len(strategy_inputs) < self.min_strategies:
            return self._create_hold_decision(
                market_context.market,
                f"Insufficient strategies ({len(strategy_inputs)} < {self.min_strategies})",
                timestamp,
            )
        
        # Convert inputs to component formats
        votes = self._convert_to_votes(strategy_inputs)
        signals = self._convert_to_signals(strategy_inputs)
        
        # Run consensus voting
        consensus_result = self.consensus_voting.vote(votes)
        
        # Run ensemble aggregation
        ensemble_result = self.ensemble_aggregator.aggregate(signals)
        
        # Determine primary signal (hybrid or consensus-only)
        if self.use_hybrid_mode:
            primary_signal, decision_method = self._hybrid_decision(
                consensus_result, ensemble_result
            )
        else:
            primary_signal = consensus_result.final_signal
            decision_method = "consensus"
        
        # Calculate confidence score for primary signal
        confidence_score = self._calculate_confidence(
            primary_signal,
            strategy_inputs,
            market_context,
            consensus_result,
            ensemble_result,
        )
        
        # Apply risk controls
        final_signal, risk_override = self._apply_risk_controls(
            primary_signal,
            confidence_score,
            market_context,
        )
        
        # Determine if should execute
        should_execute = (
            final_signal != "HOLD" and
            confidence_score.should_trade and
            not risk_override
        )
        
        # Generate reasoning
        reasoning = self._generate_reasoning(
            final_signal,
            decision_method,
            confidence_score,
            risk_override,
            market_context,
        )
        
        return FinalDecision(
            market=market_context.market,
            signal=final_signal,
            confidence=confidence_score.final_confidence,
            should_execute=should_execute,
            consensus_result=consensus_result,
            ensemble_result=ensemble_result,
            confidence_score=confidence_score,
            participating_strategies=len(strategy_inputs),
            decision_method=decision_method,
            risk_override=risk_override,
            reasoning=reasoning,
            timestamp=timestamp,
        )
    
    def _convert_to_votes(self, inputs: List[StrategyInput]) -> List[StrategyVote]:
        """Convert strategy inputs to consensus votes."""
        return [
            StrategyVote(
                strategy_id=inp.strategy_id,
                market=inp.market,
                signal=inp.signal,
                confidence=inp.confidence,
                health_score=inp.health_score,
                timestamp=inp.timestamp,
            )
            for inp in inputs
        ]
    
    def _convert_to_signals(self, inputs: List[StrategyInput]) -> List[StrategySignal]:
        """Convert strategy inputs to ensemble signals."""
        return [
            StrategySignal(
                strategy_id=inp.strategy_id,
                market=inp.market,
                signal=inp.signal,
                confidence=inp.confidence,
                strength=inp.strength,
                health_score=inp.health_score,
                sharpe_ratio=inp.sharpe_ratio,
                timestamp=inp.timestamp,
            )
            for inp in inputs
        ]
    
    def _hybrid_decision(
        self,
        consensus: ConsensusResult,
        ensemble: EnsembleSignal,
    ) -> tuple[str, str]:
        """
        Make hybrid decision combining consensus and ensemble.
        
        Returns:
            (signal, decision_method)
        """
        # If both agree, use that signal
        if consensus.final_signal == ensemble.final_signal:
            return consensus.final_signal, "hybrid_agreement"
        
        # If disagreement, use higher confidence
        if consensus.consensus_confidence > ensemble.ensemble_confidence:
            return consensus.final_signal, "hybrid_consensus_priority"
        else:
            return ensemble.final_signal, "hybrid_ensemble_priority"
    
    def _calculate_confidence(
        self,
        signal: str,
        inputs: List[StrategyInput],
        context: MarketContext,
        consensus: ConsensusResult,
        ensemble: EnsembleSignal,
    ) -> ConfidenceScore:
        """Calculate comprehensive confidence score."""
        # Find a representative strategy for this signal (highest health)
        signal_strategies = [inp for inp in inputs if inp.signal == signal]
        
        if not signal_strategies:
            # No strategies voting for this signal, use low confidence
            base_confidence = 0.3
            strategy_id = "none"
            regime_fit = 0.5
        else:
            # Use highest health strategy as representative
            best_strategy = max(signal_strategies, key=lambda x: x.health_score)
            base_confidence = best_strategy.confidence
            strategy_id = best_strategy.strategy_id
            regime_fit = best_strategy.regime_fit
        
        # Calculate ensemble agreement (how many strategies agree)
        total_strategies = len(inputs)
        agreeing_strategies = len(signal_strategies)
        ensemble_agreement = agreeing_strategies / total_strategies if total_strategies > 0 else 0.0
        
        # Score confidence
        return self.confidence_scorer.score_confidence(
            strategy_id=strategy_id,
            base_confidence=base_confidence,
            market_trend=context.trend,
            signal_direction=signal,
            current_regime=context.regime,
            strategy_regime_fit=regime_fit,
            current_volatility=context.current_volatility,
            target_volatility=context.target_volatility,
            ensemble_agreement=ensemble_agreement,
        )
    
    def _apply_risk_controls(
        self,
        signal: str,
        confidence: ConfidenceScore,
        context: MarketContext,
    ) -> tuple[str, bool]:
        """
        Apply portfolio-level risk controls.
        
        Returns:
            (final_signal, risk_override)
        """
        risk_override = False
        
        # Check portfolio risk score
        if context.portfolio_risk_score > 75:  # Critical risk
            if signal != "HOLD":
                _log.warning(
                    f"Risk override: Portfolio risk critical ({context.portfolio_risk_score:.1f})"
                )
                signal = "HOLD"
                risk_override = True
        
        # Check capital throttle
        if context.capital_throttle_level in ["heavy", "full"]:
            if signal != "HOLD":
                _log.warning(
                    f"Risk override: Capital throttle active ({context.capital_throttle_level})"
                )
                signal = "HOLD"
                risk_override = True
        
        # Check extreme volatility
        if context.current_volatility > context.target_volatility * 2.5:
            if signal != "HOLD":
                _log.warning(
                    f"Risk override: Extreme volatility "
                    f"({context.current_volatility:.2%} vs {context.target_volatility:.2%})"
                )
                signal = "HOLD"
                risk_override = True
        
        return signal, risk_override
    
    def _generate_reasoning(
        self,
        signal: str,
        method: str,
        confidence: ConfidenceScore,
        risk_override: bool,
        context: MarketContext,
    ) -> str:
        """Generate human-readable reasoning."""
        parts = [
            f"Decision: {signal}",
            f"Method: {method}",
            f"Confidence: {confidence.final_confidence:.2%}",
        ]
        
        if risk_override:
            parts.append("⚠️ RISK OVERRIDE")
        
        if context.portfolio_risk_score > 50:
            parts.append(f"Portfolio Risk: {context.portfolio_risk_score:.0f}")
        
        if context.capital_throttle_level != "none":
            parts.append(f"Throttle: {context.capital_throttle_level}")
        
        return " | ".join(parts)
    
    def _create_hold_decision(
        self,
        market: str,
        reason: str,
        timestamp: float,
    ) -> FinalDecision:
        """Create a default HOLD decision."""
        # Create empty results
        empty_consensus = ConsensusResult(
            final_signal="HOLD",
            consensus_confidence=0.0,
            agreement_score=0.0,
            participating_strategies=0,
            vote_breakdown={},
            weighted_votes={},
            dissent_detected=False,
            uncertainty_flag=True,
            reasoning=reason,
        )
        
        empty_ensemble = EnsembleSignal(
            final_signal="HOLD",
            ensemble_confidence=0.0,
            signal_strength=0.0,
            contributing_strategies=0,
            strategy_weights={},
            signal_distribution={},
            temporal_consistency=0.0,
            reasoning=reason,
        )
        
        empty_confidence = ConfidenceScore(
            final_confidence=0.0,
            confidence_level="very_low",
            factors=None,  # type: ignore
            adjustments={},
            should_trade=False,
            reasoning=reason,
        )
        
        return FinalDecision(
            market=market,
            signal="HOLD",
            confidence=0.0,
            should_execute=False,
            consensus_result=empty_consensus,
            ensemble_result=empty_ensemble,
            confidence_score=empty_confidence,
            participating_strategies=0,
            decision_method="none",
            risk_override=False,
            reasoning=reason,
            timestamp=timestamp,
        )
    
    def get_decision_summary(self, decision: FinalDecision) -> str:
        """Generate comprehensive decision summary."""
        summary = [
            f"Market: {decision.market}",
            f"Signal: {decision.signal}",
            f"Confidence: {decision.confidence:.2%}",
            f"Execute: {'YES' if decision.should_execute else 'NO'}",
            f"Method: {decision.decision_method}",
            f"Strategies: {decision.participating_strategies}",
        ]
        
        if decision.risk_override:
            summary.append("⚠️ RISK OVERRIDE")
        
        # Add consensus info
        summary.append(
            f"Consensus: {decision.consensus_result.final_signal} "
            f"({decision.consensus_result.agreement_score:.0%} agreement)"
        )
        
        # Add ensemble info
        summary.append(
            f"Ensemble: {decision.ensemble_result.final_signal} "
            f"({decision.ensemble_result.ensemble_confidence:.0%} confidence)"
        )
        
        return " | ".join(summary)
