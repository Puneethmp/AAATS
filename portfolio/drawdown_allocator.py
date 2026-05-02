"""
Drawdown Allocator

Adjusts capital allocation based on drawdown levels to protect capital.

Features:
- Drawdown-aware capital scaling
- Progressive risk reduction during drawdowns
- Recovery-based capital restoration
- Per-strategy and portfolio-level drawdown tracking
"""

from dataclasses import dataclass
from typing import Dict
from foundation.logger import logger


@dataclass
class DrawdownMetrics:
    """Drawdown metrics for portfolio or strategy"""
    current_drawdown: float  # Current drawdown as percentage (negative)
    max_drawdown: float  # Maximum historical drawdown
    days_in_drawdown: int  # Days since peak
    drawdown_severity: str  # "none", "minor", "moderate", "severe", "critical"
    capital_scaling_factor: float  # Multiplier for capital allocation (0-1)
    is_recovery: bool  # True if recovering from drawdown


class DrawdownAllocator:
    """
    Adjusts capital allocation based on drawdown severity.
    
    Drawdown severity levels:
    - None: 0% to -5%
    - Minor: -5% to -10%
    - Moderate: -10% to -15%
    - Severe: -15% to -20%
    - Critical: > -20%
    
    Capital scaling:
    - None: 100% allocation
    - Minor: 90% allocation
    - Moderate: 70% allocation
    - Severe: 50% allocation
    - Critical: 25% allocation (defensive mode)
    """
    
    # Drawdown thresholds
    MINOR_DRAWDOWN = -0.05
    MODERATE_DRAWDOWN = -0.10
    SEVERE_DRAWDOWN = -0.15
    CRITICAL_DRAWDOWN = -0.20
    
    # Capital scaling factors
    SCALING_NONE = 1.00
    SCALING_MINOR = 0.90
    SCALING_MODERATE = 0.70
    SCALING_SEVERE = 0.50
    SCALING_CRITICAL = 0.25
    
    # Recovery parameters
    RECOVERY_THRESHOLD = 0.50  # 50% recovery from max DD
    
    def __init__(self):
        """Initialize drawdown allocator"""
        self.peak_values: Dict[str, float] = {}  # Track peaks per strategy
        self.drawdown_start_dates: Dict[str, int] = {}  # Days in drawdown
        logger.info("DrawdownAllocator initialized")
    
    def update_value(self, strategy_id: str, current_value: float, days_elapsed: int = 1):
        """
        Update strategy value and track drawdown.
        
        Args:
            strategy_id: Strategy identifier (use "portfolio" for total)
            current_value: Current portfolio/strategy value
            days_elapsed: Days since last update (default: 1)
        """
        # Initialize peak if first update
        if strategy_id not in self.peak_values:
            self.peak_values[strategy_id] = current_value
            self.drawdown_start_dates[strategy_id] = 0
            return
        
        # Update peak if new high
        if current_value > self.peak_values[strategy_id]:
            self.peak_values[strategy_id] = current_value
            self.drawdown_start_dates[strategy_id] = 0  # Reset drawdown counter
        else:
            # In drawdown, increment counter
            self.drawdown_start_dates[strategy_id] += days_elapsed
    
    def calculate_drawdown_metrics(self, strategy_id: str, current_value: float) -> DrawdownMetrics:
        """
        Calculate drawdown metrics for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            current_value: Current value
            
        Returns:
            DrawdownMetrics with current drawdown and scaling factor
        """
        # Get peak value
        peak = self.peak_values.get(strategy_id, current_value)
        
        # Calculate current drawdown
        if peak > 0:
            current_dd = (current_value - peak) / peak
        else:
            current_dd = 0.0
        
        # Get days in drawdown
        days_in_dd = self.drawdown_start_dates.get(strategy_id, 0)
        
        # Determine severity
        if current_dd >= self.MINOR_DRAWDOWN:
            severity = "none"
            scaling = self.SCALING_NONE
        elif current_dd >= self.MODERATE_DRAWDOWN:
            severity = "minor"
            scaling = self.SCALING_MINOR
        elif current_dd >= self.SEVERE_DRAWDOWN:
            severity = "moderate"
            scaling = self.SCALING_MODERATE
        elif current_dd >= self.CRITICAL_DRAWDOWN:
            severity = "severe"
            scaling = self.SCALING_SEVERE
        else:
            severity = "critical"
            scaling = self.SCALING_CRITICAL
        
        # Check if recovering
        # Recovery defined as: was in drawdown, now less than 50% of max DD
        is_recovery = False
        if days_in_dd > 0 and current_dd > self.CRITICAL_DRAWDOWN:
            # Check if recovering from deeper drawdown
            if current_dd > self.SEVERE_DRAWDOWN and severity in ["none", "minor"]:
                is_recovery = True
            elif current_dd > self.MODERATE_DRAWDOWN and severity == "none":
                is_recovery = True
        
        # Get max historical drawdown (stored peak vs current)
        max_dd = current_dd  # Simplified - in production, track historical max
        
        metrics = DrawdownMetrics(
            current_drawdown=current_dd,
            max_drawdown=max_dd,
            days_in_drawdown=days_in_dd,
            drawdown_severity=severity,
            capital_scaling_factor=scaling,
            is_recovery=is_recovery
        )
        
        if severity != "none":
            logger.warning(
                f"Drawdown detected: {strategy_id}",
                extra={
                    "strategy_id": strategy_id,
                    "drawdown": current_dd,
                    "severity": severity,
                    "days_in_drawdown": days_in_dd
                }
            )
        
        return metrics
    
    def get_allocation_multiplier(
        self,
        strategy_id: str,
        current_value: float
    ) -> float:
        """
        Get capital allocation multiplier based on drawdown.
        
        Args:
            strategy_id: Strategy identifier
            current_value: Current value
            
        Returns:
            Multiplier to apply to base allocation (0.25 to 1.0)
        """
        metrics = self.calculate_drawdown_metrics(strategy_id, current_value)
        return metrics.capital_scaling_factor
    
    def should_halt_strategy(
        self,
        strategy_id: str,
        current_value: float,
        halt_threshold: float = None
    ) -> bool:
        """
        Check if strategy should be halted due to severe drawdown.
        
        Args:
            strategy_id: Strategy identifier
            current_value: Current value
            halt_threshold: Drawdown threshold for halt (default: CRITICAL_DRAWDOWN)
            
        Returns:
            True if strategy should be halted
        """
        if halt_threshold is None:
            halt_threshold = self.CRITICAL_DRAWDOWN
        
        metrics = self.calculate_drawdown_metrics(strategy_id, current_value)
        
        if metrics.current_drawdown < halt_threshold:
            logger.error(
                f"Strategy halt recommended: {strategy_id}",
                extra={
                    "strategy_id": strategy_id,
                    "drawdown": metrics.current_drawdown,
                    "threshold": halt_threshold
                }
            )
            return True
        
        return False
    
    def get_recovery_bonus(
        self,
        strategy_id: str,
        current_value: float
    ) -> float:
        """
        Get allocation bonus for strategies recovering from drawdown.
        
        Args:
            strategy_id: Strategy identifier
            current_value: Current value
            
        Returns:
            Bonus multiplier (1.0 to 1.2)
        """
        metrics = self.calculate_drawdown_metrics(strategy_id, current_value)
        
        if metrics.is_recovery:
            # Give 10-20% bonus to recovering strategies
            recovery_progress = abs(metrics.current_drawdown) / abs(self.SEVERE_DRAWDOWN)
            bonus = 1.0 + (0.2 * (1 - recovery_progress))
            
            logger.info(
                f"Recovery bonus applied: {strategy_id}",
                extra={
                    "strategy_id": strategy_id,
                    "bonus": bonus,
                    "drawdown": metrics.current_drawdown
                }
            )
            
            return min(1.2, bonus)
        
        return 1.0
    
    def get_portfolio_drawdown_action(
        self,
        portfolio_value: float
    ) -> str:
        """
        Get recommended action based on portfolio drawdown.
        
        Args:
            portfolio_value: Current portfolio value
            
        Returns:
            Action: "normal", "reduce", "defensive", "halt"
        """
        metrics = self.calculate_drawdown_metrics("portfolio", portfolio_value)
        
        if metrics.drawdown_severity == "critical":
            return "halt"
        elif metrics.drawdown_severity == "severe":
            return "defensive"
        elif metrics.drawdown_severity == "moderate":
            return "reduce"
        else:
            return "normal"
    
    def reset_strategy_peak(self, strategy_id: str, new_peak: float):
        """
        Manually reset peak value for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            new_peak: New peak value
        """
        self.peak_values[strategy_id] = new_peak
        self.drawdown_start_dates[strategy_id] = 0
        
        logger.info(
            f"Peak reset: {strategy_id}",
            extra={"strategy_id": strategy_id, "new_peak": new_peak}
        )
