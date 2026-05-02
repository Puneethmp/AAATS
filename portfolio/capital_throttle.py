"""
Capital Throttle

Dynamically throttles capital deployment during high-risk periods.

Features:
- Market stress detection
- Volatility-based throttling
- Event-driven capital reduction
- Gradual capital restoration
"""

from dataclasses import dataclass
from typing import List
from foundation.logger import logger


@dataclass
class ThrottleState:
    """Current throttle state"""
    is_throttled: bool
    throttle_level: str  # "none", "light", "moderate", "heavy", "full"
    capital_multiplier: float  # 0-1, percentage of capital to deploy
    reason: str
    triggers: List[str]  # List of active triggers


class CapitalThrottle:
    """
    Throttles capital deployment during high-risk periods.
    
    Throttle levels:
    - None: 100% capital available
    - Light: 80% capital available
    - Moderate: 60% capital available
    - Heavy: 40% capital available
    - Full: 20% capital available (defensive mode)
    
    Triggers:
    - High volatility (VIX spike, portfolio vol spike)
    - Market stress (drawdown, correlation spike)
    - External events (manual trigger)
    - Consecutive losses
    """
    
    # Throttle multipliers
    MULTIPLIER_NONE = 1.00
    MULTIPLIER_LIGHT = 0.80
    MULTIPLIER_MODERATE = 0.60
    MULTIPLIER_HEAVY = 0.40
    MULTIPLIER_FULL = 0.20
    
    # Volatility thresholds
    VOL_SPIKE_THRESHOLD = 1.5  # 50% increase in volatility
    EXTREME_VOL_THRESHOLD = 2.0  # 100% increase
    
    # Drawdown thresholds
    MODERATE_DD_THRESHOLD = -0.10
    SEVERE_DD_THRESHOLD = -0.15
    
    # Correlation threshold
    HIGH_CORRELATION_THRESHOLD = 0.8
    
    # Loss streak threshold
    MAX_CONSECUTIVE_LOSSES = 5
    
    def __init__(self):
        """Initialize capital throttle"""
        self.is_manually_throttled = False
        self.manual_throttle_level = "none"
        self.consecutive_losses = 0
        logger.info("CapitalThrottle initialized")
    
    def evaluate_throttle(
        self,
        volatility_ratio: float = 1.0,
        portfolio_drawdown: float = 0.0,
        avg_correlation: float = 0.3,
        consecutive_losses: int = 0,
        vix_level: float = None
    ) -> ThrottleState:
        """
        Evaluate whether capital should be throttled.
        
        Args:
            volatility_ratio: Current vol / Target vol
            portfolio_drawdown: Current portfolio drawdown (negative)
            avg_correlation: Average correlation between strategies
            consecutive_losses: Number of consecutive losing days
            vix_level: VIX level (optional, for US market)
            
        Returns:
            ThrottleState with throttle level and reason
        """
        triggers = []
        throttle_scores = []
        
        # Check manual throttle
        if self.is_manually_throttled:
            return ThrottleState(
                is_throttled=True,
                throttle_level=self.manual_throttle_level,
                capital_multiplier=self._get_multiplier(self.manual_throttle_level),
                reason="Manual throttle engaged",
                triggers=["manual"]
            )
        
        # Check volatility
        vol_score, vol_trigger = self._check_volatility(volatility_ratio)
        if vol_trigger:
            triggers.append(vol_trigger)
            throttle_scores.append(vol_score)
        
        # Check drawdown
        dd_score, dd_trigger = self._check_drawdown(portfolio_drawdown)
        if dd_trigger:
            triggers.append(dd_trigger)
            throttle_scores.append(dd_score)
        
        # Check correlation
        corr_score, corr_trigger = self._check_correlation(avg_correlation)
        if corr_trigger:
            triggers.append(corr_trigger)
            throttle_scores.append(corr_score)
        
        # Check loss streak
        loss_score, loss_trigger = self._check_loss_streak(consecutive_losses)
        if loss_trigger:
            triggers.append(loss_trigger)
            throttle_scores.append(loss_score)
        
        # Check VIX if provided
        if vix_level is not None:
            vix_score, vix_trigger = self._check_vix(vix_level)
            if vix_trigger:
                triggers.append(vix_trigger)
                throttle_scores.append(vix_score)
        
        # Determine overall throttle level
        if not triggers:
            throttle_level = "none"
            reason = "No throttle triggers active"
        else:
            # Use maximum throttle score
            max_score = max(throttle_scores)
            throttle_level = self._score_to_level(max_score)
            reason = f"Throttle triggered: {', '.join(triggers)}"
        
        is_throttled = throttle_level != "none"
        multiplier = self._get_multiplier(throttle_level)
        
        state = ThrottleState(
            is_throttled=is_throttled,
            throttle_level=throttle_level,
            capital_multiplier=multiplier,
            reason=reason,
            triggers=triggers
        )
        
        if is_throttled:
            logger.warning(
                f"Capital throttle engaged: {throttle_level}",
                extra={
                    "throttle_level": throttle_level,
                    "multiplier": multiplier,
                    "triggers": triggers
                }
            )
        
        return state
    
    def _check_volatility(self, volatility_ratio: float) -> tuple[int, str]:
        """
        Check volatility trigger.
        
        Returns:
            (throttle_score, trigger_description) or (0, None)
        """
        if volatility_ratio >= self.EXTREME_VOL_THRESHOLD:
            return (4, f"Extreme volatility ({volatility_ratio:.1f}x target)")
        elif volatility_ratio >= self.VOL_SPIKE_THRESHOLD:
            return (2, f"High volatility ({volatility_ratio:.1f}x target)")
        return (0, None)
    
    def _check_drawdown(self, drawdown: float) -> tuple[int, str]:
        """
        Check drawdown trigger.
        
        Returns:
            (throttle_score, trigger_description) or (0, None)
        """
        if drawdown < self.SEVERE_DD_THRESHOLD:
            return (4, f"Severe drawdown ({drawdown:.1%})")
        elif drawdown < self.MODERATE_DD_THRESHOLD:
            return (2, f"Moderate drawdown ({drawdown:.1%})")
        return (0, None)
    
    def _check_correlation(self, avg_correlation: float) -> tuple[int, str]:
        """
        Check correlation trigger.
        
        Returns:
            (throttle_score, trigger_description) or (0, None)
        """
        if avg_correlation >= self.HIGH_CORRELATION_THRESHOLD:
            return (3, f"High correlation ({avg_correlation:.2f})")
        return (0, None)
    
    def _check_loss_streak(self, consecutive_losses: int) -> tuple[int, str]:
        """
        Check loss streak trigger.
        
        Returns:
            (throttle_score, trigger_description) or (0, None)
        """
        if consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            return (3, f"Loss streak ({consecutive_losses} days)")
        return (0, None)
    
    def _check_vix(self, vix_level: float) -> tuple[int, str]:
        """
        Check VIX trigger.
        
        Returns:
            (throttle_score, trigger_description) or (0, None)
        """
        if vix_level >= 40:
            return (4, f"Extreme VIX ({vix_level:.1f})")
        elif vix_level >= 30:
            return (3, f"High VIX ({vix_level:.1f})")
        elif vix_level >= 25:
            return (1, f"Elevated VIX ({vix_level:.1f})")
        return (0, None)
    
    def _score_to_level(self, score: int) -> str:
        """Convert throttle score to level"""
        if score >= 4:
            return "full"
        elif score >= 3:
            return "heavy"
        elif score >= 2:
            return "moderate"
        elif score >= 1:
            return "light"
        else:
            return "none"
    
    def _get_multiplier(self, level: str) -> float:
        """Get capital multiplier for throttle level"""
        multipliers = {
            "none": self.MULTIPLIER_NONE,
            "light": self.MULTIPLIER_LIGHT,
            "moderate": self.MULTIPLIER_MODERATE,
            "heavy": self.MULTIPLIER_HEAVY,
            "full": self.MULTIPLIER_FULL
        }
        return multipliers.get(level, self.MULTIPLIER_NONE)
    
    def engage_manual_throttle(self, level: str = "moderate"):
        """
        Manually engage throttle.
        
        Args:
            level: Throttle level ("light", "moderate", "heavy", "full")
        """
        self.is_manually_throttled = True
        self.manual_throttle_level = level
        
        logger.warning(
            f"Manual throttle engaged: {level}",
            extra={"throttle_level": level}
        )
    
    def release_manual_throttle(self):
        """Release manual throttle"""
        self.is_manually_throttled = False
        self.manual_throttle_level = "none"
        
        logger.info("Manual throttle released")
    
    def update_consecutive_losses(self, is_loss: bool):
        """
        Update consecutive loss counter.
        
        Args:
            is_loss: True if today was a losing day
        """
        if is_loss:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
    
    def get_throttle_recommendation(
        self,
        current_state: ThrottleState
    ) -> str:
        """
        Get recommendation based on throttle state.
        
        Args:
            current_state: Current throttle state
            
        Returns:
            Recommendation string
        """
        if not current_state.is_throttled:
            return "Normal operations - full capital deployment"
        
        if current_state.throttle_level == "light":
            return "Light throttle - reduce new positions by 20%"
        elif current_state.throttle_level == "moderate":
            return "Moderate throttle - reduce new positions by 40%, consider closing weak positions"
        elif current_state.throttle_level == "heavy":
            return "Heavy throttle - reduce new positions by 60%, close underperforming positions"
        else:  # full
            return "Full throttle - defensive mode, minimal new positions, preserve capital"
