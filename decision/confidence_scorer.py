"""
Advanced confidence scoring system for trading signals.

Implements multi-factor confidence assessment:
  - Market condition alignment
  - Historical accuracy tracking
  - Regime-specific performance
  - Volatility-adjusted confidence
  - Cross-validation with other signals
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import time

import numpy as np

from foundation.logger import get_logger

_log = get_logger("decision", "confidence_scorer")


@dataclass
class ConfidenceFactors:
    """Individual confidence factors."""
    base_confidence: float  # Strategy's raw confidence (0.0-1.0)
    market_alignment: float  # How well signal aligns with market (0.0-1.0)
    historical_accuracy: float  # Strategy's historical accuracy (0.0-1.0)
    regime_fit: float  # Fit with current regime (0.0-1.0)
    volatility_adjustment: float  # Volatility-based adjustment (0.5-1.5)
    cross_validation: float  # Agreement with other signals (0.0-1.0)


@dataclass
class ConfidenceScore:
    """Final confidence score with breakdown."""
    final_confidence: float  # 0.0-1.0
    confidence_level: str  # "very_low", "low", "medium", "high", "very_high"
    factors: ConfidenceFactors
    adjustments: Dict[str, float]  # Factor name -> contribution
    should_trade: bool  # Whether confidence is sufficient
    reasoning: str


class ConfidenceScorer:
    """
    Multi-factor confidence scoring engine.
    
    Features:
      - Market condition alignment scoring
      - Historical accuracy tracking per strategy
      - Regime-specific performance weighting
      - Volatility-based confidence adjustment
      - Cross-validation with ensemble signals
    """
    
    def __init__(
        self,
        min_confidence_threshold: float = 0.6,
        market_weight: float = 0.15,
        history_weight: float = 0.25,
        regime_weight: float = 0.20,
        volatility_weight: float = 0.15,
        cross_validation_weight: float = 0.25,
    ):
        """
        Initialize confidence scorer.
        
        Args:
            min_confidence_threshold: Minimum confidence to trade (0.6 = 60%)
            market_weight: Weight for market alignment (15%)
            history_weight: Weight for historical accuracy (25%)
            regime_weight: Weight for regime fit (20%)
            volatility_weight: Weight for volatility adjustment (15%)
            cross_validation_weight: Weight for cross-validation (25%)
        """
        self.min_confidence_threshold = min_confidence_threshold
        self.market_weight = market_weight
        self.history_weight = history_weight
        self.regime_weight = regime_weight
        self.volatility_weight = volatility_weight
        self.cross_validation_weight = cross_validation_weight
        
        # Track historical accuracy per strategy
        self.accuracy_history: Dict[str, List[bool]] = {}  # strategy_id -> [outcomes]
        self.max_history_length = 100
        
        _log.info(
            f"Initialized confidence scorer: "
            f"threshold={min_confidence_threshold:.2f}, "
            f"weights=[market={market_weight:.2f}, history={history_weight:.2f}, "
            f"regime={regime_weight:.2f}, vol={volatility_weight:.2f}, "
            f"cross_val={cross_validation_weight:.2f}]"
        )
    
    def score_confidence(
        self,
        strategy_id: str,
        base_confidence: float,
        market_trend: str,  # "bullish", "bearish", "neutral"
        signal_direction: str,  # "BUY", "SELL", "HOLD"
        current_regime: str,  # "bull_trend", "bear_trend", "sideways", etc.
        strategy_regime_fit: float,  # 0.0-1.0
        current_volatility: float,  # Annualized volatility
        target_volatility: float,  # Target volatility
        ensemble_agreement: float,  # 0.0-1.0
    ) -> ConfidenceScore:
        """
        Calculate comprehensive confidence score.
        
        Args:
            strategy_id: Strategy identifier
            base_confidence: Strategy's raw confidence (0.0-1.0)
            market_trend: Current market trend
            signal_direction: Signal direction
            current_regime: Current market regime
            strategy_regime_fit: How well strategy fits regime (0.0-1.0)
            current_volatility: Current market volatility
            target_volatility: Target volatility level
            ensemble_agreement: Agreement with other strategies (0.0-1.0)
        
        Returns:
            ConfidenceScore with final score and breakdown
        """
        # Calculate individual factors
        market_alignment = self._calculate_market_alignment(
            market_trend, signal_direction
        )
        
        historical_accuracy = self._get_historical_accuracy(strategy_id)
        
        regime_fit = strategy_regime_fit
        
        volatility_adjustment = self._calculate_volatility_adjustment(
            current_volatility, target_volatility
        )
        
        cross_validation = ensemble_agreement
        
        # Create factors object
        factors = ConfidenceFactors(
            base_confidence=base_confidence,
            market_alignment=market_alignment,
            historical_accuracy=historical_accuracy,
            regime_fit=regime_fit,
            volatility_adjustment=volatility_adjustment,
            cross_validation=cross_validation,
        )
        
        # Calculate weighted adjustments
        adjustments = {
            "market": market_alignment * self.market_weight,
            "history": historical_accuracy * self.history_weight,
            "regime": regime_fit * self.regime_weight,
            "volatility": (volatility_adjustment - 1.0) * self.volatility_weight,
            "cross_validation": cross_validation * self.cross_validation_weight,
        }
        
        # Calculate final confidence
        # Start with base, then apply weighted adjustments
        adjustment_sum = sum(adjustments.values())
        final_confidence = base_confidence * (1.0 + adjustment_sum)
        
        # Clip to valid range
        final_confidence = np.clip(final_confidence, 0.0, 1.0)
        
        # Determine confidence level
        confidence_level = self._classify_confidence_level(final_confidence)
        
        # Determine if should trade
        should_trade = final_confidence >= self.min_confidence_threshold
        
        # Generate reasoning
        reasoning = self._generate_reasoning(
            final_confidence, factors, adjustments, should_trade
        )
        
        return ConfidenceScore(
            final_confidence=final_confidence,
            confidence_level=confidence_level,
            factors=factors,
            adjustments=adjustments,
            should_trade=should_trade,
            reasoning=reasoning,
        )
    
    def _calculate_market_alignment(
        self, market_trend: str, signal_direction: str
    ) -> float:
        """
        Calculate how well signal aligns with market trend.
        
        Returns:
            Alignment score (0.0-1.0)
        """
        # Perfect alignment
        if (market_trend == "bullish" and signal_direction == "BUY") or \
           (market_trend == "bearish" and signal_direction == "SELL"):
            return 1.0
        
        # Neutral market or HOLD signal
        if market_trend == "neutral" or signal_direction == "HOLD":
            return 0.7
        
        # Counter-trend (contrarian)
        if (market_trend == "bullish" and signal_direction == "SELL") or \
           (market_trend == "bearish" and signal_direction == "BUY"):
            return 0.4  # Lower but not zero (contrarian can work)
        
        return 0.5  # Default
    
    def _get_historical_accuracy(self, strategy_id: str) -> float:
        """
        Get historical accuracy for strategy.
        
        Returns:
            Accuracy score (0.0-1.0)
        """
        history = self.accuracy_history.get(strategy_id, [])
        
        if not history:
            return 0.7  # Default for new strategies
        
        # Calculate win rate
        wins = sum(1 for outcome in history if outcome)
        accuracy = wins / len(history)
        
        return accuracy
    
    def _calculate_volatility_adjustment(
        self, current_vol: float, target_vol: float
    ) -> float:
        """
        Calculate volatility-based confidence adjustment.
        
        Returns:
            Multiplier (0.5-1.5)
        """
        if target_vol == 0:
            return 1.0
        
        vol_ratio = current_vol / target_vol
        
        # Low volatility (< 0.7x target): Boost confidence slightly
        if vol_ratio < 0.7:
            return 1.2
        
        # Normal volatility (0.7x - 1.3x target): No adjustment
        if 0.7 <= vol_ratio <= 1.3:
            return 1.0
        
        # High volatility (1.3x - 2.0x target): Reduce confidence
        if 1.3 < vol_ratio <= 2.0:
            return 0.8
        
        # Extreme volatility (> 2.0x target): Significantly reduce
        return 0.5
    
    def _classify_confidence_level(self, confidence: float) -> str:
        """Classify confidence into discrete levels."""
        if confidence >= 0.85:
            return "very_high"
        elif confidence >= 0.70:
            return "high"
        elif confidence >= 0.55:
            return "medium"
        elif confidence >= 0.40:
            return "low"
        else:
            return "very_low"
    
    def _generate_reasoning(
        self,
        final_confidence: float,
        factors: ConfidenceFactors,
        adjustments: Dict[str, float],
        should_trade: bool,
    ) -> str:
        """Generate human-readable reasoning."""
        reasoning_parts = [
            f"Confidence: {final_confidence:.2%}",
            f"Base: {factors.base_confidence:.2%}",
        ]
        
        # Highlight significant adjustments
        significant_adjustments = [
            (k, v) for k, v in adjustments.items() if abs(v) > 0.05
        ]
        
        if significant_adjustments:
            adj_str = ", ".join(
                f"{k}={v:+.2%}" for k, v in significant_adjustments
            )
            reasoning_parts.append(f"Adjustments: {adj_str}")
        
        # Add trade decision
        if should_trade:
            reasoning_parts.append("✓ Trade approved")
        else:
            reasoning_parts.append("✗ Below threshold")
        
        return " | ".join(reasoning_parts)
    
    def update_accuracy(
        self, strategy_id: str, was_successful: bool
    ) -> None:
        """
        Update historical accuracy for strategy.
        
        Args:
            strategy_id: Strategy identifier
            was_successful: Whether the trade was successful
        """
        if strategy_id not in self.accuracy_history:
            self.accuracy_history[strategy_id] = []
        
        history = self.accuracy_history[strategy_id]
        history.append(was_successful)
        
        # Keep only recent history
        if len(history) > self.max_history_length:
            history.pop(0)
        
        current_accuracy = sum(history) / len(history)
        _log.debug(
            f"Updated accuracy for {strategy_id}: "
            f"{current_accuracy:.2%} ({len(history)} trades)"
        )
    
    def get_strategy_accuracy(self, strategy_id: str) -> Optional[float]:
        """Get current accuracy for strategy."""
        history = self.accuracy_history.get(strategy_id, [])
        if not history:
            return None
        return sum(history) / len(history)
    
    def get_confidence_summary(self, score: ConfidenceScore) -> str:
        """Generate detailed confidence summary."""
        summary = [
            f"Confidence: {score.final_confidence:.2%} ({score.confidence_level})",
            f"Base: {score.factors.base_confidence:.2%}",
            f"Market: {score.factors.market_alignment:.2%}",
            f"History: {score.factors.historical_accuracy:.2%}",
            f"Regime: {score.factors.regime_fit:.2%}",
            f"Vol Adj: {score.factors.volatility_adjustment:.2f}x",
            f"Cross-Val: {score.factors.cross_validation:.2%}",
            f"Trade: {'YES' if score.should_trade else 'NO'}",
        ]
        
        return " | ".join(summary)
    
    def reset_accuracy_history(self, strategy_id: Optional[str] = None) -> None:
        """
        Reset accuracy history.
        
        Args:
            strategy_id: Specific strategy to reset, or None for all
        """
        if strategy_id:
            self.accuracy_history.pop(strategy_id, None)
            _log.info(f"Reset accuracy history for {strategy_id}")
        else:
            self.accuracy_history.clear()
            _log.info("Reset all accuracy history")
