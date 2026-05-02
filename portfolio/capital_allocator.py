"""
Capital Allocator

Adaptive capital allocation based on strategy health scores and performance.

Allocation Strategy:
- Allocates capital proportionally to strategy health scores
- Respects per-market and per-strategy limits
- Adjusts allocations based on recent performance
- Maintains minimum and maximum allocation bounds
"""

from dataclasses import dataclass
from typing import Dict, List
import numpy as np
from foundation.logger import logger
from portfolio.strategy_health import HealthScore


@dataclass
class AllocationConstraints:
    """Constraints for capital allocation"""
    total_capital: float
    max_deployment_pct: float = 0.40  # Max 40% deployed across all strategies
    min_strategy_allocation: float = 0.01  # Min 1% per strategy
    max_strategy_allocation: float = 0.10  # Max 10% per strategy
    min_cash_reserve: float = 0.20  # Min 20% cash reserve
    
    # Per-market allocation limits
    max_us_allocation: float = 0.40
    max_india_equity_allocation: float = 0.40
    max_india_fo_allocation: float = 0.20
    max_crypto_allocation: float = 0.20


@dataclass
class StrategyAllocation:
    """Capital allocation for a strategy"""
    strategy_id: str
    market: str
    allocated_capital: float
    allocation_pct: float  # Percentage of total capital
    health_score: float
    previous_allocation: float
    change_pct: float
    reason: str


class CapitalAllocator:
    """
    Allocates capital across strategies based on health scores.
    
    Allocation methodology:
    1. Filter strategies by health score threshold
    2. Calculate allocation weights based on health scores
    3. Apply per-strategy and per-market constraints
    4. Ensure minimum cash reserve
    5. Smooth allocation changes to avoid churn
    """
    
    # Allocation parameters
    MIN_HEALTH_SCORE_FOR_ALLOCATION = 50.0  # Don't allocate to strategies below this
    ALLOCATION_SMOOTHING_FACTOR = 0.3  # 30% of change applied per rebalance
    
    def __init__(self, constraints: AllocationConstraints):
        """
        Initialize capital allocator.
        
        Args:
            constraints: Allocation constraints and limits
        """
        self.constraints = constraints
        self.current_allocations: Dict[str, float] = {}
        logger.info(
            "CapitalAllocator initialized",
            extra={
                "total_capital": constraints.total_capital,
                "max_deployment": constraints.max_deployment_pct
            }
        )
    
    def allocate_capital(
        self,
        health_scores: Dict[str, HealthScore]
    ) -> List[StrategyAllocation]:
        """
        Allocate capital across strategies based on health scores.
        
        Args:
            health_scores: Dictionary mapping strategy_id to HealthScore
            
        Returns:
            List of StrategyAllocation objects
        """
        # Filter strategies by minimum health score
        eligible_strategies = {
            sid: score for sid, score in health_scores.items()
            if score.overall_score >= self.MIN_HEALTH_SCORE_FOR_ALLOCATION
            and score.recommendation in ["increase", "maintain"]
        }
        
        if not eligible_strategies:
            logger.warning("No eligible strategies for capital allocation")
            return []
        
        # Calculate raw allocation weights based on health scores
        raw_weights = self._calculate_raw_weights(eligible_strategies)
        
        # Apply per-market constraints
        constrained_weights = self._apply_market_constraints(
            raw_weights, eligible_strategies
        )
        
        # Apply per-strategy constraints
        final_weights = self._apply_strategy_constraints(constrained_weights)
        
        # Calculate actual capital allocations
        allocations = self._calculate_allocations(
            final_weights, eligible_strategies
        )
        
        # Update current allocations
        for alloc in allocations:
            self.current_allocations[alloc.strategy_id] = alloc.allocated_capital
        
        logger.info(
            f"Capital allocated to {len(allocations)} strategies",
            extra={
                "total_allocated": sum(a.allocated_capital for a in allocations),
                "allocation_pct": sum(a.allocation_pct for a in allocations)
            }
        )
        
        return allocations
    
    def _calculate_raw_weights(
        self,
        health_scores: Dict[str, HealthScore]
    ) -> Dict[str, float]:
        """
        Calculate raw allocation weights based on health scores.
        
        Uses exponential weighting to favor higher-scoring strategies.
        """
        weights = {}
        total_score = sum(score.overall_score for score in health_scores.values())
        
        if total_score == 0:
            # Equal weight if all scores are zero
            equal_weight = 1.0 / len(health_scores)
            return {sid: equal_weight for sid in health_scores.keys()}
        
        for strategy_id, score in health_scores.items():
            # Exponential weighting: higher scores get disproportionately more
            exp_score = np.exp(score.overall_score / 50)  # Normalize to ~2 for score=100
            weights[strategy_id] = exp_score
        
        # Normalize to sum to 1
        total_weight = sum(weights.values())
        weights = {sid: w / total_weight for sid, w in weights.items()}
        
        return weights
    
    def _apply_market_constraints(
        self,
        weights: Dict[str, float],
        health_scores: Dict[str, HealthScore]
    ) -> Dict[str, float]:
        """Apply per-market allocation constraints"""
        # Group strategies by market
        market_groups = {}
        for strategy_id, score in health_scores.items():
            market = score.market
            if market not in market_groups:
                market_groups[market] = []
            market_groups[market].append(strategy_id)
        
        # Calculate market limits
        market_limits = {
            "us": self.constraints.max_us_allocation,
            "india": self.constraints.max_india_equity_allocation,
            "india_fo": self.constraints.max_india_fo_allocation,
            "crypto": self.constraints.max_crypto_allocation
        }
        
        constrained_weights = weights.copy()
        
        # Check each market's total allocation
        for market, strategy_ids in market_groups.items():
            market_total = sum(weights.get(sid, 0) for sid in strategy_ids)
            market_limit = market_limits.get(market, 0.40)
            
            if market_total > market_limit:
                # Scale down this market's allocations proportionally
                scale_factor = market_limit / market_total
                for sid in strategy_ids:
                    constrained_weights[sid] = weights[sid] * scale_factor
        
        # Renormalize
        total_weight = sum(constrained_weights.values())
        if total_weight > 0:
            constrained_weights = {
                sid: w / total_weight for sid, w in constrained_weights.items()
            }
        
        return constrained_weights
    
    def _apply_strategy_constraints(
        self,
        weights: Dict[str, float]
    ) -> Dict[str, float]:
        """Apply per-strategy min/max constraints"""
        constrained_weights = {}
        
        for strategy_id, weight in weights.items():
            # Apply min/max bounds
            constrained_weight = max(
                self.constraints.min_strategy_allocation,
                min(weight, self.constraints.max_strategy_allocation)
            )
            constrained_weights[strategy_id] = constrained_weight
        
        # Renormalize
        total_weight = sum(constrained_weights.values())
        if total_weight > 0:
            constrained_weights = {
                sid: w / total_weight for sid, w in constrained_weights.items()
            }
        
        return constrained_weights
    
    def _calculate_allocations(
        self,
        weights: Dict[str, float],
        health_scores: Dict[str, HealthScore]
    ) -> List[StrategyAllocation]:
        """Calculate final capital allocations with smoothing"""
        allocations = []
        
        # Total deployable capital (respecting max deployment and cash reserve)
        max_deployable = self.constraints.total_capital * min(
            self.constraints.max_deployment_pct,
            1.0 - self.constraints.min_cash_reserve
        )
        
        for strategy_id, weight in weights.items():
            score = health_scores[strategy_id]
            
            # Calculate target allocation
            target_allocation = max_deployable * weight
            
            # Get previous allocation
            previous_allocation = self.current_allocations.get(strategy_id, 0.0)
            
            # Apply smoothing to avoid churn
            if previous_allocation > 0:
                change = target_allocation - previous_allocation
                smoothed_change = change * self.ALLOCATION_SMOOTHING_FACTOR
                allocated_capital = previous_allocation + smoothed_change
            else:
                # New allocation, no smoothing
                allocated_capital = target_allocation
            
            # Calculate percentage and change
            allocation_pct = allocated_capital / self.constraints.total_capital
            change_pct = (
                (allocated_capital - previous_allocation) / previous_allocation * 100
                if previous_allocation > 0 else 100.0
            )
            
            # Determine reason
            if previous_allocation == 0:
                reason = "New allocation"
            elif change_pct > 5:
                reason = f"Increased by {change_pct:.1f}%"
            elif change_pct < -5:
                reason = f"Decreased by {abs(change_pct):.1f}%"
            else:
                reason = "Maintained"
            
            allocation = StrategyAllocation(
                strategy_id=strategy_id,
                market=score.market,
                allocated_capital=allocated_capital,
                allocation_pct=allocation_pct,
                health_score=score.overall_score,
                previous_allocation=previous_allocation,
                change_pct=change_pct,
                reason=reason
            )
            
            allocations.append(allocation)
        
        return allocations
    
    def get_unallocated_capital(self) -> float:
        """Get remaining unallocated capital"""
        allocated = sum(self.current_allocations.values())
        return self.constraints.total_capital - allocated
    
    def get_allocation_summary(self) -> Dict:
        """Get summary of current allocations"""
        total_allocated = sum(self.current_allocations.values())
        allocation_pct = total_allocated / self.constraints.total_capital
        
        return {
            "total_capital": self.constraints.total_capital,
            "total_allocated": total_allocated,
            "allocation_pct": allocation_pct,
            "unallocated": self.constraints.total_capital - total_allocated,
            "num_strategies": len(self.current_allocations),
            "strategies": self.current_allocations.copy()
        }
