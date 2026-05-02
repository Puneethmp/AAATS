"""
Volatility Targeting

Adjusts portfolio exposure to maintain target volatility level.

Features:
- Portfolio volatility calculation
- Dynamic position sizing based on volatility
- Volatility regime detection
- Risk scaling during high volatility periods
"""

from dataclasses import dataclass
from typing import List
import numpy as np
from foundation.logger import logger


@dataclass
class VolatilityMetrics:
    """Portfolio volatility metrics"""
    current_volatility: float  # Annualized portfolio volatility
    target_volatility: float
    volatility_ratio: float  # Current / Target
    realized_volatility_30d: float
    volatility_trend: str  # "increasing", "decreasing", "stable"
    regime: str  # "low", "normal", "high", "extreme"
    scaling_factor: float  # Position size multiplier


class VolatilityTargeting:
    """
    Maintains target portfolio volatility through dynamic position sizing.
    
    Volatility regimes:
    - Low: < 10% annualized
    - Normal: 10-20% annualized
    - High: 20-30% annualized
    - Extreme: > 30% annualized
    """
    
    # Volatility parameters
    TARGET_VOLATILITY = 0.15  # 15% annualized target
    MIN_VOLATILITY = 0.05  # 5% minimum
    MAX_VOLATILITY = 0.30  # 30% maximum
    
    # Regime thresholds
    LOW_VOL_THRESHOLD = 0.10
    NORMAL_VOL_THRESHOLD = 0.20
    HIGH_VOL_THRESHOLD = 0.30
    
    # Scaling parameters
    MIN_SCALING_FACTOR = 0.25  # Minimum 25% of normal size
    MAX_SCALING_FACTOR = 2.00  # Maximum 200% of normal size
    
    def __init__(self, target_volatility: float = None):
        """
        Initialize volatility targeting.
        
        Args:
            target_volatility: Target annualized volatility (default: 0.15)
        """
        self.target_volatility = target_volatility or self.TARGET_VOLATILITY
        self.returns_history: List[float] = []
        logger.info(
            "VolatilityTargeting initialized",
            extra={"target_volatility": self.target_volatility}
        )
    
    def update_returns(self, daily_return: float):
        """
        Update portfolio returns history.
        
        Args:
            daily_return: Daily portfolio return (e.g., 0.01 for 1%)
        """
        self.returns_history.append(daily_return)
        
        # Keep only recent history (252 trading days = 1 year)
        if len(self.returns_history) > 252:
            self.returns_history = self.returns_history[-252:]
    
    def calculate_volatility_metrics(
        self,
        lookback_days: int = 60
    ) -> VolatilityMetrics:
        """
        Calculate current portfolio volatility metrics.
        
        Args:
            lookback_days: Number of days for volatility calculation
            
        Returns:
            VolatilityMetrics with current volatility and scaling factor
        """
        if len(self.returns_history) < 20:
            # Insufficient data, return neutral metrics
            return VolatilityMetrics(
                current_volatility=self.target_volatility,
                target_volatility=self.target_volatility,
                volatility_ratio=1.0,
                realized_volatility_30d=self.target_volatility,
                volatility_trend="stable",
                regime="normal",
                scaling_factor=1.0
            )
        
        # Calculate current volatility (annualized)
        recent_returns = np.array(self.returns_history[-lookback_days:])
        current_vol = np.std(recent_returns) * np.sqrt(252)
        
        # Calculate 30-day realized volatility
        if len(self.returns_history) >= 30:
            recent_30d = np.array(self.returns_history[-30:])
            realized_vol_30d = np.std(recent_30d) * np.sqrt(252)
        else:
            realized_vol_30d = current_vol
        
        # Determine volatility trend
        if len(self.returns_history) >= 120:
            older_returns = np.array(self.returns_history[-120:-60])
            older_vol = np.std(older_returns) * np.sqrt(252)
            
            if current_vol > older_vol * 1.2:
                trend = "increasing"
            elif current_vol < older_vol * 0.8:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        # Determine volatility regime
        if current_vol < self.LOW_VOL_THRESHOLD:
            regime = "low"
        elif current_vol < self.NORMAL_VOL_THRESHOLD:
            regime = "normal"
        elif current_vol < self.HIGH_VOL_THRESHOLD:
            regime = "high"
        else:
            regime = "extreme"
        
        # Calculate volatility ratio
        vol_ratio = current_vol / self.target_volatility if current_vol > 0 else 1.0
        
        # Calculate scaling factor (inverse of volatility ratio)
        # If volatility is 2x target, scale positions to 0.5x
        raw_scaling = 1.0 / vol_ratio if vol_ratio > 0 else 1.0
        
        # Apply bounds
        scaling_factor = max(
            self.MIN_SCALING_FACTOR,
            min(self.MAX_SCALING_FACTOR, raw_scaling)
        )
        
        metrics = VolatilityMetrics(
            current_volatility=current_vol,
            target_volatility=self.target_volatility,
            volatility_ratio=vol_ratio,
            realized_volatility_30d=realized_vol_30d,
            volatility_trend=trend,
            regime=regime,
            scaling_factor=scaling_factor
        )
        
        logger.info(
            "Volatility metrics calculated",
            extra={
                "current_volatility": current_vol,
                "regime": regime,
                "scaling_factor": scaling_factor
            }
        )
        
        return metrics
    
    def get_position_size_multiplier(self) -> float:
        """
        Get current position size multiplier based on volatility.
        
        Returns:
            Multiplier to apply to base position sizes (0.25 to 2.0)
        """
        metrics = self.calculate_volatility_metrics()
        return metrics.scaling_factor
    
    def should_reduce_exposure(self, threshold: float = 1.5) -> bool:
        """
        Check if exposure should be reduced due to high volatility.
        
        Args:
            threshold: Volatility ratio threshold for reduction
            
        Returns:
            True if volatility exceeds threshold
        """
        metrics = self.calculate_volatility_metrics()
        
        if metrics.volatility_ratio > threshold:
            logger.warning(
                f"High volatility detected: {metrics.current_volatility:.1%}",
                extra={
                    "current_volatility": metrics.current_volatility,
                    "target_volatility": self.target_volatility,
                    "ratio": metrics.volatility_ratio
                }
            )
            return True
        
        return False
    
    def get_regime_based_limits(self) -> dict:
        """
        Get position limits based on volatility regime.
        
        Returns:
            Dictionary with regime-specific limits
        """
        metrics = self.calculate_volatility_metrics()
        
        if metrics.regime == "low":
            return {
                "max_position_size": 0.12,  # 12% per position
                "max_portfolio_exposure": 0.50,  # 50% total
                "max_leverage": 1.2
            }
        elif metrics.regime == "normal":
            return {
                "max_position_size": 0.10,  # 10% per position
                "max_portfolio_exposure": 0.40,  # 40% total
                "max_leverage": 1.0
            }
        elif metrics.regime == "high":
            return {
                "max_position_size": 0.07,  # 7% per position
                "max_portfolio_exposure": 0.30,  # 30% total
                "max_leverage": 0.8
            }
        else:  # extreme
            return {
                "max_position_size": 0.05,  # 5% per position
                "max_portfolio_exposure": 0.20,  # 20% total
                "max_leverage": 0.5
            }
    
    def calculate_var(self, confidence: float = 0.95) -> float:
        """
        Calculate Value at Risk (VaR) at given confidence level.
        
        Args:
            confidence: Confidence level (e.g., 0.95 for 95%)
            
        Returns:
            VaR as percentage of portfolio
        """
        if len(self.returns_history) < 20:
            return 0.0
        
        returns = np.array(self.returns_history)
        var = np.percentile(returns, (1 - confidence) * 100)
        
        logger.debug(
            f"VaR calculated: {var:.2%} at {confidence:.0%} confidence",
            extra={"var": var, "confidence": confidence}
        )
        
        return var
    
    def calculate_cvar(self, confidence: float = 0.95) -> float:
        """
        Calculate Conditional Value at Risk (CVaR/Expected Shortfall).
        
        Args:
            confidence: Confidence level (e.g., 0.95 for 95%)
            
        Returns:
            CVaR as percentage of portfolio
        """
        if len(self.returns_history) < 20:
            return 0.0
        
        returns = np.array(self.returns_history)
        var = self.calculate_var(confidence)
        
        # CVaR is the average of returns below VaR
        tail_returns = returns[returns <= var]
        cvar = np.mean(tail_returns) if len(tail_returns) > 0 else var
        
        logger.debug(
            f"CVaR calculated: {cvar:.2%} at {confidence:.0%} confidence",
            extra={"cvar": cvar, "confidence": confidence}
        )
        
        return cvar
