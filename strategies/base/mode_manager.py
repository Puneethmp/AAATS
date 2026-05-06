"""
Mode Manager — Handles strategy mode transitions (paper → shadow → live).

Ensures safe transitions and validates readiness before mode changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from foundation.logger import get_logger
from strategies.base.strategy_base import StrategyMode

_log = get_logger("strategies", "mode_manager")


@dataclass
class ModeTransitionCriteria:
    """Criteria for transitioning between modes."""
    
    # Paper → Shadow transition
    min_paper_trades: int = 100
    min_paper_days: int = 14
    min_paper_win_rate: float = 0.45
    max_paper_drawdown: float = 0.15
    
    # Shadow → Live transition
    min_shadow_trades: int = 200
    min_shadow_days: int = 30
    min_shadow_win_rate: float = 0.50
    max_shadow_drawdown: float = 0.10
    min_shadow_sharpe: float = 1.0


@dataclass
class StrategyPerformance:
    """Strategy performance metrics for mode transition validation."""
    total_trades: int = 0
    days_active: int = 0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    total_pnl: float = 0.0
    last_updated: datetime | None = None


class ModeManager:
    """
    Manages strategy mode transitions.
    
    Ensures strategies meet performance criteria before transitioning
    from paper → shadow → live.
    """
    
    def __init__(self, criteria: ModeTransitionCriteria | None = None):
        """
        Initialize mode manager.
        
        Args:
            criteria: Transition criteria (uses defaults if None)
        """
        self.criteria = criteria or ModeTransitionCriteria()
        self._log = _log
    
    def can_transition_to_shadow(
        self,
        performance: StrategyPerformance,
    ) -> tuple[bool, str]:
        """
        Check if strategy can transition from paper to shadow mode.
        
        Args:
            performance: Strategy performance metrics
        
        Returns:
            Tuple of (can_transition, reason)
        """
        # Check minimum trades
        if performance.total_trades < self.criteria.min_paper_trades:
            return False, (
                f"Insufficient trades: {performance.total_trades} < "
                f"{self.criteria.min_paper_trades}"
            )
        
        # Check minimum days
        if performance.days_active < self.criteria.min_paper_days:
            return False, (
                f"Insufficient days: {performance.days_active} < "
                f"{self.criteria.min_paper_days}"
            )
        
        # Check win rate
        if performance.win_rate < self.criteria.min_paper_win_rate:
            return False, (
                f"Low win rate: {performance.win_rate:.1%} < "
                f"{self.criteria.min_paper_win_rate:.1%}"
            )
        
        # Check drawdown
        if performance.max_drawdown > self.criteria.max_paper_drawdown:
            return False, (
                f"High drawdown: {performance.max_drawdown:.1%} > "
                f"{self.criteria.max_paper_drawdown:.1%}"
            )
        
        return True, "All paper trading criteria met"
    
    def can_transition_to_live(
        self,
        performance: StrategyPerformance,
    ) -> tuple[bool, str]:
        """
        Check if strategy can transition from shadow to live mode.
        
        Args:
            performance: Strategy performance metrics
        
        Returns:
            Tuple of (can_transition, reason)
        """
        # Check minimum trades
        if performance.total_trades < self.criteria.min_shadow_trades:
            return False, (
                f"Insufficient trades: {performance.total_trades} < "
                f"{self.criteria.min_shadow_trades}"
            )
        
        # Check minimum days
        if performance.days_active < self.criteria.min_shadow_days:
            return False, (
                f"Insufficient days: {performance.days_active} < "
                f"{self.criteria.min_shadow_days}"
            )
        
        # Check win rate
        if performance.win_rate < self.criteria.min_shadow_win_rate:
            return False, (
                f"Low win rate: {performance.win_rate:.1%} < "
                f"{self.criteria.min_shadow_win_rate:.1%}"
            )
        
        # Check drawdown
        if performance.max_drawdown > self.criteria.max_shadow_drawdown:
            return False, (
                f"High drawdown: {performance.max_drawdown:.1%} > "
                f"{self.criteria.max_shadow_drawdown:.1%}"
            )
        
        # Check Sharpe ratio
        if performance.sharpe_ratio < self.criteria.min_shadow_sharpe:
            return False, (
                f"Low Sharpe ratio: {performance.sharpe_ratio:.2f} < "
                f"{self.criteria.min_shadow_sharpe:.2f}"
            )
        
        return True, "All shadow trading criteria met"
    
    def validate_transition(
        self,
        current_mode: StrategyMode,
        target_mode: StrategyMode,
        performance: StrategyPerformance,
    ) -> tuple[bool, str]:
        """
        Validate a mode transition.
        
        Args:
            current_mode: Current strategy mode
            target_mode: Target strategy mode
            performance: Strategy performance metrics
        
        Returns:
            Tuple of (is_valid, reason)
        """
        # Research mode can always transition to paper
        if current_mode == StrategyMode.RESEARCH and target_mode == StrategyMode.PAPER:
            return True, "Research → Paper transition allowed"
        
        # Paper → Shadow transition
        if current_mode == StrategyMode.PAPER and target_mode == StrategyMode.SHADOW:
            return self.can_transition_to_shadow(performance)
        
        # Shadow → Live transition
        if current_mode == StrategyMode.SHADOW and target_mode == StrategyMode.LIVE:
            return self.can_transition_to_live(performance)
        
        # Backward transitions (live → shadow → paper) always allowed
        mode_order = [StrategyMode.RESEARCH, StrategyMode.PAPER, StrategyMode.SHADOW, StrategyMode.LIVE]
        current_idx = mode_order.index(current_mode)
        target_idx = mode_order.index(target_mode)
        
        if target_idx < current_idx:
            return True, f"Backward transition {current_mode.value} → {target_mode.value} allowed"
        
        # Invalid transition
        return False, f"Invalid transition: {current_mode.value} → {target_mode.value}"
    
    def get_transition_progress(
        self,
        current_mode: StrategyMode,
        performance: StrategyPerformance,
    ) -> dict[str, float]:
        """
        Get progress toward next mode transition.
        
        Args:
            current_mode: Current strategy mode
            performance: Strategy performance metrics
        
        Returns:
            Dictionary of progress percentages (0.0-1.0) for each criterion
        """
        if current_mode == StrategyMode.PAPER:
            return {
                "trades": min(1.0, performance.total_trades / self.criteria.min_paper_trades),
                "days": min(1.0, performance.days_active / self.criteria.min_paper_days),
                "win_rate": min(1.0, performance.win_rate / self.criteria.min_paper_win_rate),
                "drawdown": min(1.0, (self.criteria.max_paper_drawdown - performance.max_drawdown) / self.criteria.max_paper_drawdown),
            }
        
        elif current_mode == StrategyMode.SHADOW:
            return {
                "trades": min(1.0, performance.total_trades / self.criteria.min_shadow_trades),
                "days": min(1.0, performance.days_active / self.criteria.min_shadow_days),
                "win_rate": min(1.0, performance.win_rate / self.criteria.min_shadow_win_rate),
                "drawdown": min(1.0, (self.criteria.max_shadow_drawdown - performance.max_drawdown) / self.criteria.max_shadow_drawdown),
                "sharpe": min(1.0, performance.sharpe_ratio / self.criteria.min_shadow_sharpe),
            }
        
        return {}


# Global singleton
_mode_manager = ModeManager()


def validate_transition(
    current_mode: StrategyMode,
    target_mode: StrategyMode,
    performance: StrategyPerformance,
) -> tuple[bool, str]:
    """Convenience function using global mode manager."""
    return _mode_manager.validate_transition(current_mode, target_mode, performance)


def get_transition_progress(
    current_mode: StrategyMode,
    performance: StrategyPerformance,
) -> dict[str, float]:
    """Convenience function using global mode manager."""
    return _mode_manager.get_transition_progress(current_mode, performance)
