"""
Regime Allocator

Adjusts capital allocation based on market regime.

Features:
- Regime-aware strategy selection
- Dynamic allocation based on regime fit
- Regime transition detection
- Strategy-regime performance tracking
"""

from dataclasses import dataclass
from typing import Dict, List
from foundation.logger import logger


@dataclass
class RegimeAllocation:
    """Allocation recommendation for a regime"""
    regime: str
    recommended_strategies: List[str]
    allocation_weights: Dict[str, float]
    confidence: float  # 0-1, confidence in regime classification
    regime_duration: int  # Days in current regime
    transition_risk: str  # "low", "moderate", "high"


class RegimeAllocator:
    """
    Allocates capital based on market regime.
    
    Supported regimes:
    - Bull Trend: Favor momentum, breakout strategies
    - Bear Trend: Favor short strategies, defensive positions
    - Sideways: Favor mean reversion, range-bound strategies
    - High Volatility: Favor volatility strategies, reduce exposure
    """
    
    # Regime-strategy mappings
    REGIME_STRATEGY_MAP = {
        "bull_trend": {
            "momentum": 0.40,
            "breakout": 0.30,
            "trend_following": 0.20,
            "mean_reversion": 0.10
        },
        "bear_trend": {
            "short_momentum": 0.30,
            "defensive": 0.30,
            "mean_reversion": 0.25,
            "volatility": 0.15
        },
        "sideways": {
            "mean_reversion": 0.45,
            "range_bound": 0.30,
            "volatility_compression": 0.15,
            "momentum": 0.10
        },
        "high_volatility": {
            "volatility": 0.40,
            "defensive": 0.30,
            "mean_reversion": 0.20,
            "momentum": 0.10
        }
    }
    
    # Transition risk thresholds
    SHORT_REGIME_DURATION = 5  # Days
    MODERATE_REGIME_DURATION = 15  # Days
    
    def __init__(self):
        """Initialize regime allocator"""
        self.current_regime = "sideways"
        self.regime_start_day = 0
        self.regime_history: List[str] = []
        logger.info("RegimeAllocator initialized")
    
    def update_regime(self, new_regime: str, days_elapsed: int = 1):
        """
        Update current market regime.
        
        Args:
            new_regime: New regime classification
            days_elapsed: Days since last update
        """
        if new_regime != self.current_regime:
            # Regime transition
            logger.info(
                f"Regime transition: {self.current_regime} -> {new_regime}",
                extra={
                    "old_regime": self.current_regime,
                    "new_regime": new_regime,
                    "duration": self.regime_start_day
                }
            )
            self.regime_history.append(self.current_regime)
            self.current_regime = new_regime
            self.regime_start_day = 0
        else:
            self.regime_start_day += days_elapsed
        
        # Keep only recent history (last 10 regimes)
        if len(self.regime_history) > 10:
            self.regime_history = self.regime_history[-10:]
    
    def get_regime_allocation(
        self,
        regime: str = None,
        regime_confidence: float = 0.8
    ) -> RegimeAllocation:
        """
        Get allocation recommendation for current regime.
        
        Args:
            regime: Market regime (default: current regime)
            regime_confidence: Confidence in regime classification (0-1)
            
        Returns:
            RegimeAllocation with strategy recommendations
        """
        if regime is None:
            regime = self.current_regime
        
        # Get base allocation weights for regime
        base_weights = self.REGIME_STRATEGY_MAP.get(
            regime,
            self.REGIME_STRATEGY_MAP["sideways"]  # Default to sideways
        )
        
        # Adjust weights based on confidence
        adjusted_weights = self._adjust_for_confidence(base_weights, regime_confidence)
        
        # Determine transition risk
        transition_risk = self._assess_transition_risk()
        
        # Get recommended strategies (sorted by weight)
        recommended_strategies = sorted(
            adjusted_weights.keys(),
            key=lambda x: adjusted_weights[x],
            reverse=True
        )
        
        allocation = RegimeAllocation(
            regime=regime,
            recommended_strategies=recommended_strategies,
            allocation_weights=adjusted_weights,
            confidence=regime_confidence,
            regime_duration=self.regime_start_day,
            transition_risk=transition_risk
        )
        
        logger.info(
            f"Regime allocation calculated: {regime}",
            extra={
                "regime": regime,
                "top_strategy": recommended_strategies[0] if recommended_strategies else None,
                "confidence": regime_confidence,
                "transition_risk": transition_risk
            }
        )
        
        return allocation
    
    def get_strategy_multiplier(
        self,
        strategy_type: str,
        regime: str = None
    ) -> float:
        """
        Get allocation multiplier for a strategy type in current regime.
        
        Args:
            strategy_type: Strategy type (e.g., "momentum", "mean_reversion")
            regime: Market regime (default: current regime)
            
        Returns:
            Multiplier (0.5 to 2.0)
        """
        if regime is None:
            regime = self.current_regime
        
        # Get regime weights
        regime_weights = self.REGIME_STRATEGY_MAP.get(
            regime,
            self.REGIME_STRATEGY_MAP["sideways"]
        )
        
        # Get weight for this strategy type
        weight = regime_weights.get(strategy_type, 0.1)  # Default 10% if not found
        
        # Convert weight to multiplier (0.5 to 2.0)
        # Weight 0.10 -> 0.5x, Weight 0.40 -> 2.0x
        multiplier = 0.5 + (weight / 0.40) * 1.5
        multiplier = max(0.5, min(2.0, multiplier))
        
        return multiplier
    
    def should_reduce_exposure(self) -> bool:
        """
        Check if exposure should be reduced due to regime uncertainty.
        
        Returns:
            True if exposure should be reduced
        """
        # Reduce exposure in high volatility regime
        if self.current_regime == "high_volatility":
            return True
        
        # Reduce exposure during regime transitions (first 5 days)
        if self.regime_start_day < self.SHORT_REGIME_DURATION:
            transition_risk = self._assess_transition_risk()
            if transition_risk == "high":
                logger.warning(
                    "Exposure reduction recommended: regime transition",
                    extra={
                        "regime": self.current_regime,
                        "duration": self.regime_start_day,
                        "transition_risk": transition_risk
                    }
                )
                return True
        
        return False
    
    def _adjust_for_confidence(
        self,
        base_weights: Dict[str, float],
        confidence: float
    ) -> Dict[str, float]:
        """
        Adjust allocation weights based on regime confidence.
        
        Low confidence -> more balanced allocation
        High confidence -> more concentrated allocation
        """
        if confidence >= 0.8:
            # High confidence, use base weights
            return base_weights.copy()
        
        # Low confidence, blend with equal weights
        equal_weight = 1.0 / len(base_weights)
        adjusted_weights = {}
        
        for strategy, weight in base_weights.items():
            # Blend: (confidence * base_weight) + ((1-confidence) * equal_weight)
            adjusted_weight = (confidence * weight) + ((1 - confidence) * equal_weight)
            adjusted_weights[strategy] = adjusted_weight
        
        # Renormalize
        total = sum(adjusted_weights.values())
        adjusted_weights = {k: v / total for k, v in adjusted_weights.items()}
        
        return adjusted_weights
    
    def _assess_transition_risk(self) -> str:
        """
        Assess risk of regime transition.
        
        Returns:
            "low", "moderate", or "high"
        """
        # High risk if regime is very new
        if self.regime_start_day < self.SHORT_REGIME_DURATION:
            return "high"
        
        # Moderate risk if regime is relatively new
        if self.regime_start_day < self.MODERATE_REGIME_DURATION:
            return "moderate"
        
        # Check for frequent regime changes in history
        if len(self.regime_history) >= 5:
            recent_changes = len(set(self.regime_history[-5:]))
            if recent_changes >= 4:
                # 4+ different regimes in last 5 periods = unstable
                return "high"
            elif recent_changes >= 3:
                return "moderate"
        
        return "low"
    
    def get_regime_statistics(self) -> Dict:
        """
        Get statistics about regime history.
        
        Returns:
            Dictionary with regime statistics
        """
        return {
            "current_regime": self.current_regime,
            "regime_duration": self.regime_start_day,
            "transition_risk": self._assess_transition_risk(),
            "regime_history": self.regime_history[-5:],  # Last 5 regimes
            "regime_stability": self._calculate_stability()
        }
    
    def _calculate_stability(self) -> float:
        """
        Calculate regime stability score (0-1).
        
        Higher score = more stable regime
        """
        if len(self.regime_history) < 3:
            return 0.5  # Neutral if insufficient history
        
        # Count unique regimes in recent history
        recent_regimes = self.regime_history[-5:]
        unique_count = len(set(recent_regimes))
        
        # Stability inversely related to unique count
        # 1 unique = 1.0 stability, 5 unique = 0.0 stability
        stability = 1.0 - ((unique_count - 1) / 4.0)
        
        # Bonus for long current regime duration
        if self.regime_start_day > 30:
            stability = min(1.0, stability + 0.2)
        
        return stability
