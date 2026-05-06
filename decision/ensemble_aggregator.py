"""
Ensemble signal aggregation for combining multiple strategy signals.

Implements sophisticated signal combination techniques:
  - Weighted averaging by strategy performance
  - Bayesian confidence aggregation
  - Signal strength normalization
  - Temporal consistency checking
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import time

import numpy as np

from foundation.logger import get_logger

_log = get_logger("decision", "ensemble_aggregator")


@dataclass
class StrategySignal:
    """Individual strategy signal with metadata."""
    strategy_id: str
    market: str
    signal: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0.0-1.0
    strength: float  # Signal strength (e.g., distance from threshold)
    health_score: float  # 0-100
    sharpe_ratio: float  # Strategy performance metric
    timestamp: float


@dataclass
class EnsembleSignal:
    """Aggregated ensemble signal."""
    final_signal: str  # "BUY", "SELL", "HOLD"
    ensemble_confidence: float  # 0.0-1.0
    signal_strength: float  # Aggregated strength
    contributing_strategies: int
    strategy_weights: Dict[str, float]  # Strategy ID -> weight
    signal_distribution: Dict[str, float]  # Signal type -> weighted score
    temporal_consistency: float  # 0.0-1.0
    reasoning: str


class EnsembleAggregator:
    """
    Ensemble signal aggregation engine.
    
    Features:
      - Performance-weighted signal combination
      - Bayesian confidence aggregation
      - Signal strength normalization
      - Temporal consistency tracking
      - Adaptive weight adjustment
    """
    
    def __init__(
        self,
        min_strategies: int = 3,
        performance_weight: float = 0.6,
        health_weight: float = 0.4,
        temporal_window: int = 5,
    ):
        """
        Initialize ensemble aggregator.
        
        Args:
            min_strategies: Minimum strategies required for ensemble
            performance_weight: Weight for Sharpe ratio (0.6 = 60%)
            health_weight: Weight for health score (0.4 = 40%)
            temporal_window: Number of recent signals to track for consistency
        """
        self.min_strategies = min_strategies
        self.performance_weight = performance_weight
        self.health_weight = health_weight
        self.temporal_window = temporal_window
        
        # Track recent signals for temporal consistency
        self.signal_history: Dict[str, List[str]] = {}  # strategy_id -> [signals]
        
        _log.info(
            f"Initialized ensemble aggregator: "
            f"min_strategies={min_strategies}, "
            f"perf_weight={performance_weight:.2f}, "
            f"health_weight={health_weight:.2f}"
        )
    
    def aggregate(self, signals: List[StrategySignal]) -> EnsembleSignal:
        """
        Aggregate multiple strategy signals into ensemble decision.
        
        Args:
            signals: List of strategy signals
        
        Returns:
            EnsembleSignal with aggregated decision
        """
        if len(signals) < self.min_strategies:
            return EnsembleSignal(
                final_signal="HOLD",
                ensemble_confidence=0.0,
                signal_strength=0.0,
                contributing_strategies=len(signals),
                strategy_weights={},
                signal_distribution={},
                temporal_consistency=0.0,
                reasoning=f"Insufficient strategies ({len(signals)} < {self.min_strategies})"
            )
        
        # Calculate strategy weights
        weights = self._calculate_strategy_weights(signals)
        
        # Calculate weighted signal distribution
        signal_dist = self._calculate_signal_distribution(signals, weights)
        
        # Determine final signal
        final_signal = max(signal_dist.items(), key=lambda x: x[1])[0]
        
        # Calculate ensemble confidence (Bayesian aggregation)
        ensemble_confidence = self._aggregate_confidence(signals, weights, final_signal)
        
        # Calculate aggregated signal strength
        signal_strength = self._aggregate_strength(signals, weights, final_signal)
        
        # Calculate temporal consistency
        temporal_consistency = self._calculate_temporal_consistency(signals)
        
        # Update signal history
        self._update_signal_history(signals)
        
        # Generate reasoning
        reasoning = self._generate_reasoning(
            final_signal, signal_dist, temporal_consistency
        )
        
        return EnsembleSignal(
            final_signal=final_signal,
            ensemble_confidence=ensemble_confidence,
            signal_strength=signal_strength,
            contributing_strategies=len(signals),
            strategy_weights=weights,
            signal_distribution=signal_dist,
            temporal_consistency=temporal_consistency,
            reasoning=reasoning
        )
    
    def _calculate_strategy_weights(
        self, signals: List[StrategySignal]
    ) -> Dict[str, float]:
        """
        Calculate adaptive weights for each strategy.
        
        Weight = (Sharpe × perf_weight) + (Health/100 × health_weight)
        Normalized to sum to 1.0
        """
        weights = {}
        
        for signal in signals:
            # Normalize Sharpe ratio (clip to 0-3 range, then scale to 0-1)
            normalized_sharpe = np.clip(signal.sharpe_ratio, 0, 3) / 3.0
            
            # Normalize health score (0-100 to 0-1)
            normalized_health = signal.health_score / 100.0
            
            # Combined weight
            weight = (
                normalized_sharpe * self.performance_weight +
                normalized_health * self.health_weight
            )
            
            weights[signal.strategy_id] = max(weight, 0.01)  # Minimum weight
        
        # Normalize to sum to 1.0
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {k: v / total_weight for k, v in weights.items()}
        
        return weights
    
    def _calculate_signal_distribution(
        self, signals: List[StrategySignal], weights: Dict[str, float]
    ) -> Dict[str, float]:
        """
        Calculate weighted distribution of signals.
        
        Returns:
            Dict of signal type -> weighted score
        """
        distribution = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        
        for signal in signals:
            weight = weights.get(signal.strategy_id, 0.0)
            # Weight by confidence as well
            weighted_score = weight * signal.confidence
            distribution[signal.signal] += weighted_score
        
        return distribution
    
    def _aggregate_confidence(
        self,
        signals: List[StrategySignal],
        weights: Dict[str, float],
        final_signal: str,
    ) -> float:
        """
        Aggregate confidence using Bayesian approach.
        
        Weighted average of confidences for strategies voting for final_signal.
        """
        relevant_signals = [s for s in signals if s.signal == final_signal]
        
        if not relevant_signals:
            return 0.0
        
        # Weighted average
        weighted_conf = sum(
            s.confidence * weights.get(s.strategy_id, 0.0)
            for s in relevant_signals
        )
        
        total_weight = sum(
            weights.get(s.strategy_id, 0.0) for s in relevant_signals
        )
        
        if total_weight == 0:
            return 0.0
        
        return weighted_conf / total_weight
    
    def _aggregate_strength(
        self,
        signals: List[StrategySignal],
        weights: Dict[str, float],
        final_signal: str,
    ) -> float:
        """
        Aggregate signal strength for final signal.
        
        Weighted average of signal strengths.
        """
        relevant_signals = [s for s in signals if s.signal == final_signal]
        
        if not relevant_signals:
            return 0.0
        
        weighted_strength = sum(
            s.strength * weights.get(s.strategy_id, 0.0)
            for s in relevant_signals
        )
        
        total_weight = sum(
            weights.get(s.strategy_id, 0.0) for s in relevant_signals
        )
        
        if total_weight == 0:
            return 0.0
        
        return weighted_strength / total_weight
    
    def _calculate_temporal_consistency(
        self, signals: List[StrategySignal]
    ) -> float:
        """
        Calculate temporal consistency score (0.0-1.0).
        
        Measures how consistent each strategy's signals are over time.
        """
        if not self.signal_history:
            return 1.0  # No history yet, assume consistent
        
        consistency_scores = []
        
        for signal in signals:
            history = self.signal_history.get(signal.strategy_id, [])
            
            if len(history) < 2:
                consistency_scores.append(1.0)
                continue
            
            # Calculate consistency: ratio of matching signals
            current_signal = signal.signal
            matches = sum(1 for h in history if h == current_signal)
            consistency = matches / len(history)
            consistency_scores.append(consistency)
        
        return np.mean(consistency_scores) if consistency_scores else 1.0
    
    def _update_signal_history(self, signals: List[StrategySignal]) -> None:
        """Update signal history for temporal consistency tracking."""
        for signal in signals:
            if signal.strategy_id not in self.signal_history:
                self.signal_history[signal.strategy_id] = []
            
            history = self.signal_history[signal.strategy_id]
            history.append(signal.signal)
            
            # Keep only recent window
            if len(history) > self.temporal_window:
                history.pop(0)
    
    def _generate_reasoning(
        self,
        final_signal: str,
        signal_dist: Dict[str, float],
        temporal_consistency: float,
    ) -> str:
        """Generate human-readable reasoning for ensemble decision."""
        # Calculate signal strength percentages
        total = sum(signal_dist.values())
        if total == 0:
            return "No clear signal"
        
        percentages = {k: (v / total) * 100 for k, v in signal_dist.items()}
        
        reasoning = f"Ensemble: {final_signal} ({percentages[final_signal]:.1f}%)"
        
        if temporal_consistency < 0.7:
            reasoning += " | ⚠️ Low temporal consistency"
        
        return reasoning
    
    def get_ensemble_summary(self, result: EnsembleSignal) -> str:
        """Generate detailed ensemble summary."""
        summary = [
            f"Signal: {result.final_signal}",
            f"Confidence: {result.ensemble_confidence:.2%}",
            f"Strength: {result.signal_strength:.2f}",
            f"Strategies: {result.contributing_strategies}",
            f"Consistency: {result.temporal_consistency:.2%}",
        ]
        
        # Add distribution
        dist_str = ", ".join(
            f"{k}={v:.2f}" for k, v in result.signal_distribution.items()
        )
        summary.append(f"Distribution: {dist_str}")
        
        return " | ".join(summary)
    
    def reset_history(self) -> None:
        """Reset signal history (useful for testing or regime changes)."""
        self.signal_history.clear()
        _log.info("Signal history reset")
