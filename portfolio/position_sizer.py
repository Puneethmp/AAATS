"""
Adaptive Position Sizer

Dynamically sizes positions based on multiple factors:
- Strategy health
- Portfolio volatility
- Drawdown state
- Correlation with existing positions
- Market regime

Integrates with other portfolio intelligence modules for holistic sizing.
"""

from dataclasses import dataclass
from typing import Optional
from foundation.logger import logger


@dataclass
class PositionSizeRecommendation:
    """Position size recommendation"""
    strategy_id: str
    base_size: float  # Base position size
    adjusted_size: float  # Final adjusted size
    size_pct: float  # Percentage of portfolio
    health_multiplier: float
    volatility_multiplier: float
    drawdown_multiplier: float
    correlation_multiplier: float
    regime_multiplier: float
    final_multiplier: float
    reason: str


class AdaptivePositionSizer:
    """
    Calculates adaptive position sizes based on multiple risk factors.
    
    Position sizing formula:
    Final Size = Base Size × Health × Volatility × Drawdown × Correlation × Regime
    
    Each multiplier ranges from 0.25 to 2.0, with 1.0 being neutral.
    """
    
    # Base position size limits
    MIN_POSITION_SIZE = 0.01  # 1% minimum
    MAX_POSITION_SIZE = 0.10  # 10% maximum
    DEFAULT_BASE_SIZE = 0.05  # 5% default
    
    # Multiplier bounds
    MIN_MULTIPLIER = 0.25
    MAX_MULTIPLIER = 2.00
    
    def __init__(self, portfolio_capital: float):
        """
        Initialize adaptive position sizer.
        
        Args:
            portfolio_capital: Total portfolio capital
        """
        self.portfolio_capital = portfolio_capital
        logger.info(
            "AdaptivePositionSizer initialized",
            extra={"portfolio_capital": portfolio_capital}
        )
    
    def calculate_position_size(
        self,
        strategy_id: str,
        base_size_pct: float = None,
        health_score: float = 75.0,
        volatility_ratio: float = 1.0,
        drawdown_severity: str = "none",
        correlation_with_portfolio: float = 0.3,
        regime_alignment: float = 0.8
    ) -> PositionSizeRecommendation:
        """
        Calculate adaptive position size for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            base_size_pct: Base position size as % of portfolio (default: 0.05)
            health_score: Strategy health score (0-100)
            volatility_ratio: Current vol / Target vol
            drawdown_severity: "none", "minor", "moderate", "severe", "critical"
            correlation_with_portfolio: Correlation with existing positions (0-1)
            regime_alignment: How well strategy fits current regime (0-1)
            
        Returns:
            PositionSizeRecommendation with final size and breakdown
        """
        # Set base size
        if base_size_pct is None:
            base_size_pct = self.DEFAULT_BASE_SIZE
        
        base_size_pct = max(self.MIN_POSITION_SIZE, min(self.MAX_POSITION_SIZE, base_size_pct))
        
        # Calculate multipliers
        health_mult = self._calculate_health_multiplier(health_score)
        vol_mult = self._calculate_volatility_multiplier(volatility_ratio)
        dd_mult = self._calculate_drawdown_multiplier(drawdown_severity)
        corr_mult = self._calculate_correlation_multiplier(correlation_with_portfolio)
        regime_mult = self._calculate_regime_multiplier(regime_alignment)
        
        # Calculate final multiplier
        final_mult = health_mult * vol_mult * dd_mult * corr_mult * regime_mult
        
        # Apply bounds
        final_mult = max(self.MIN_MULTIPLIER, min(self.MAX_MULTIPLIER, final_mult))
        
        # Calculate final size
        adjusted_size_pct = base_size_pct * final_mult
        adjusted_size_pct = max(self.MIN_POSITION_SIZE, min(self.MAX_POSITION_SIZE, adjusted_size_pct))
        
        # Convert to dollar amount
        base_size = base_size_pct * self.portfolio_capital
        adjusted_size = adjusted_size_pct * self.portfolio_capital
        
        # Generate reason
        reason = self._generate_sizing_reason(
            health_mult, vol_mult, dd_mult, corr_mult, regime_mult, final_mult
        )
        
        recommendation = PositionSizeRecommendation(
            strategy_id=strategy_id,
            base_size=base_size,
            adjusted_size=adjusted_size,
            size_pct=adjusted_size_pct,
            health_multiplier=health_mult,
            volatility_multiplier=vol_mult,
            drawdown_multiplier=dd_mult,
            correlation_multiplier=corr_mult,
            regime_multiplier=regime_mult,
            final_multiplier=final_mult,
            reason=reason
        )
        
        logger.info(
            f"Position size calculated: {strategy_id}",
            extra={
                "strategy_id": strategy_id,
                "base_size": base_size,
                "adjusted_size": adjusted_size,
                "final_multiplier": final_mult
            }
        )
        
        return recommendation
    
    def _calculate_health_multiplier(self, health_score: float) -> float:
        """
        Calculate multiplier based on strategy health score.
        
        Health score mapping:
        - 90-100: 1.5x (excellent)
        - 75-90: 1.2x (good)
        - 60-75: 1.0x (neutral)
        - 50-60: 0.7x (moderate)
        - <50: 0.4x (poor)
        """
        if health_score >= 90:
            return 1.5
        elif health_score >= 75:
            return 1.2
        elif health_score >= 60:
            return 1.0
        elif health_score >= 50:
            return 0.7
        else:
            return 0.4
    
    def _calculate_volatility_multiplier(self, volatility_ratio: float) -> float:
        """
        Calculate multiplier based on volatility ratio.
        
        Inverse relationship: higher volatility = smaller positions
        - Vol ratio 0.5: 1.5x (low vol, increase size)
        - Vol ratio 1.0: 1.0x (target vol, neutral)
        - Vol ratio 1.5: 0.7x (high vol, reduce size)
        - Vol ratio 2.0+: 0.5x (extreme vol, significantly reduce)
        """
        if volatility_ratio <= 0:
            return 1.0
        
        # Inverse relationship
        multiplier = 1.0 / volatility_ratio
        
        # Apply bounds
        return max(0.5, min(1.5, multiplier))
    
    def _calculate_drawdown_multiplier(self, drawdown_severity: str) -> float:
        """
        Calculate multiplier based on drawdown severity.
        
        Drawdown mapping:
        - none: 1.0x
        - minor: 0.9x
        - moderate: 0.7x
        - severe: 0.5x
        - critical: 0.3x
        """
        severity_map = {
            "none": 1.0,
            "minor": 0.9,
            "moderate": 0.7,
            "severe": 0.5,
            "critical": 0.3
        }
        return severity_map.get(drawdown_severity, 1.0)
    
    def _calculate_correlation_multiplier(self, correlation: float) -> float:
        """
        Calculate multiplier based on correlation with existing positions.
        
        Lower correlation = better diversification = larger size
        - Correlation < 0.3: 1.2x (low correlation, good diversification)
        - Correlation 0.3-0.5: 1.0x (moderate correlation, neutral)
        - Correlation 0.5-0.7: 0.8x (high correlation, reduce)
        - Correlation > 0.7: 0.6x (very high correlation, significantly reduce)
        """
        if correlation < 0.3:
            return 1.2
        elif correlation < 0.5:
            return 1.0
        elif correlation < 0.7:
            return 0.8
        else:
            return 0.6
    
    def _calculate_regime_multiplier(self, regime_alignment: float) -> float:
        """
        Calculate multiplier based on regime alignment.
        
        Higher alignment = strategy fits current regime better = larger size
        - Alignment > 0.8: 1.3x (excellent fit)
        - Alignment 0.6-0.8: 1.1x (good fit)
        - Alignment 0.4-0.6: 1.0x (neutral)
        - Alignment 0.2-0.4: 0.8x (poor fit)
        - Alignment < 0.2: 0.5x (very poor fit)
        """
        if regime_alignment > 0.8:
            return 1.3
        elif regime_alignment > 0.6:
            return 1.1
        elif regime_alignment > 0.4:
            return 1.0
        elif regime_alignment > 0.2:
            return 0.8
        else:
            return 0.5
    
    def _generate_sizing_reason(
        self,
        health_mult: float,
        vol_mult: float,
        dd_mult: float,
        corr_mult: float,
        regime_mult: float,
        final_mult: float
    ) -> str:
        """Generate human-readable reason for sizing decision"""
        reasons = []
        
        if health_mult > 1.1:
            reasons.append("strong health")
        elif health_mult < 0.9:
            reasons.append("weak health")
        
        if vol_mult < 0.9:
            reasons.append("high volatility")
        elif vol_mult > 1.1:
            reasons.append("low volatility")
        
        if dd_mult < 0.9:
            reasons.append("drawdown protection")
        
        if corr_mult < 0.9:
            reasons.append("high correlation")
        elif corr_mult > 1.1:
            reasons.append("good diversification")
        
        if regime_mult > 1.1:
            reasons.append("regime aligned")
        elif regime_mult < 0.9:
            reasons.append("regime misaligned")
        
        if not reasons:
            return f"Neutral sizing (multiplier: {final_mult:.2f})"
        
        return f"{', '.join(reasons)} (multiplier: {final_mult:.2f})"
    
    def update_portfolio_capital(self, new_capital: float):
        """Update portfolio capital"""
        self.portfolio_capital = new_capital
        logger.info(
            "Portfolio capital updated",
            extra={"new_capital": new_capital}
        )
