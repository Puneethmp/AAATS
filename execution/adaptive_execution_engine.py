"""
Adaptive Execution Engine — Execution Intelligence Layer

Coordinates intelligent order execution by:
- Integrating smart routing with quality tracking
- Adapting execution strategy based on real-time feedback
- Learning from execution history
- Optimizing for minimal slippage and market impact

Part of Phase 8: Execution Intelligence
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
import logging

from execution.smart_order_router import SmartOrderRouter, OrderUrgency, RoutingDecision
from execution.execution_quality_tracker import ExecutionQualityTracker

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRequest:
    """Request for order execution"""
    order_id: str
    symbol: str
    side: str
    quantity: float
    current_price: float
    volatility: float
    avg_daily_volume: float
    urgency: OrderUrgency = OrderUrgency.NORMAL
    max_slippage_bps: Optional[float] = None  # Maximum acceptable slippage


@dataclass
class ExecutionResult:
    """Result of order execution"""
    order_id: str
    success: bool
    quantity_filled: float
    fill_price: float
    venue: str
    order_type: str
    slippage_bps: float
    routing_decision: RoutingDecision
    execution_time_seconds: float
    reason: str


class AdaptiveExecutionEngine:
    """
    Adaptive execution engine that learns from execution history.
    
    Combines:
    - Smart order routing (venue selection, order type)
    - Execution quality tracking (slippage, fill rates)
    - Adaptive learning (adjusts thresholds based on performance)
    
    Continuously improves execution quality by:
    - Tracking venue performance
    - Adjusting routing parameters
    - Learning optimal execution strategies per market condition
    """
    
    def __init__(
        self,
        market: str,
        enable_adaptive_learning: bool = True,
        learning_rate: float = 0.1
    ):
        """
        Initialize adaptive execution engine.
        
        Args:
            market: Market identifier ("us", "india", "crypto")
            enable_adaptive_learning: Whether to adapt parameters based on feedback
            learning_rate: How quickly to adapt (0.0-1.0)
        """
        self.market = market
        self.enable_adaptive_learning = enable_adaptive_learning
        self.learning_rate = learning_rate
        
        # Initialize components
        self.router = SmartOrderRouter(market=market)
        self.quality_tracker = ExecutionQualityTracker(max_history=1000)
        
        # Adaptive parameters (adjusted based on performance)
        self.adaptive_volatility_threshold = 0.03
        self.adaptive_liquidity_threshold = 0.01
        
        logger.info(
            f"AdaptiveExecutionEngine initialized for {market}: "
            f"adaptive_learning={enable_adaptive_learning}, "
            f"learning_rate={learning_rate}"
        )
    
    def execute_order(
        self,
        request: ExecutionRequest,
        simulate: bool = False
    ) -> ExecutionResult:
        """
        Execute an order with intelligent routing and quality tracking.
        
        Args:
            request: Execution request with order details
            simulate: If True, simulate execution (for testing)
        
        Returns:
            ExecutionResult with execution details
        """
        start_time = datetime.now()
        
        # Get routing decision
        routing_decision = self.router.route_order(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            current_price=request.current_price,
            volatility=request.volatility,
            avg_daily_volume=request.avg_daily_volume,
            time_of_day=start_time,
            urgency=request.urgency
        )
        
        # Estimate expected slippage
        order_size_ratio = (request.quantity * request.current_price) / (
            request.avg_daily_volume * request.current_price
        )
        estimated_slippage = self.quality_tracker.estimate_market_impact(
            order_size_ratio=order_size_ratio,
            market_volatility=request.volatility
        )
        
        # Check if estimated slippage exceeds maximum
        if request.max_slippage_bps and estimated_slippage > request.max_slippage_bps:
            logger.warning(
                f"Order {request.order_id}: Estimated slippage {estimated_slippage:.1f}bps "
                f"exceeds max {request.max_slippage_bps:.1f}bps - rejecting"
            )
            return ExecutionResult(
                order_id=request.order_id,
                success=False,
                quantity_filled=0.0,
                fill_price=0.0,
                venue=routing_decision.venue,
                order_type=routing_decision.order_type,
                slippage_bps=0.0,
                routing_decision=routing_decision,
                execution_time_seconds=0.0,
                reason=f"Estimated slippage {estimated_slippage:.1f}bps exceeds max {request.max_slippage_bps:.1f}bps"
            )
        
        # Execute order (or simulate)
        if simulate:
            # Simulate execution
            fill_price, quantity_filled = self._simulate_execution(
                request, routing_decision, estimated_slippage
            )
            success = quantity_filled > 0
        else:
            # Real execution would go here
            # For now, simulate
            fill_price, quantity_filled = self._simulate_execution(
                request, routing_decision, estimated_slippage
            )
            success = quantity_filled > 0
        
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        # Calculate actual slippage
        if request.side == "buy":
            actual_slippage = (fill_price - request.current_price) / request.current_price * 10000
        else:
            actual_slippage = (request.current_price - fill_price) / request.current_price * 10000
        
        # Record execution for quality tracking
        self.quality_tracker.record_execution(
            order_id=request.order_id,
            symbol=request.symbol,
            side=request.side,
            quantity_requested=request.quantity,
            quantity_filled=quantity_filled,
            expected_price=routing_decision.limit_price or request.current_price,
            fill_price=fill_price,
            venue=routing_decision.venue,
            order_type=routing_decision.order_type,
            timestamp_submitted=start_time,
            timestamp_filled=end_time if success else None,
            market_volatility=request.volatility,
            order_size_ratio=order_size_ratio
        )
        
        # Update venue quality in router
        if success:
            # Calculate fill quality score (0-1)
            fill_quality = self._calculate_fill_quality(
                quantity_filled / request.quantity,
                actual_slippage,
                execution_time
            )
            self.router.update_venue_quality(routing_decision.venue, fill_quality)
        
        # Adaptive learning: adjust parameters based on performance
        if self.enable_adaptive_learning and success:
            self._adapt_parameters(actual_slippage, request.volatility, order_size_ratio)
        
        result = ExecutionResult(
            order_id=request.order_id,
            success=success,
            quantity_filled=quantity_filled,
            fill_price=fill_price,
            venue=routing_decision.venue,
            order_type=routing_decision.order_type,
            slippage_bps=actual_slippage,
            routing_decision=routing_decision,
            execution_time_seconds=execution_time,
            reason=routing_decision.reason if success else "Execution failed"
        )
        
        logger.info(
            f"Executed {request.order_id}: {request.symbol} {request.side} "
            f"{quantity_filled}/{request.quantity} @ {fill_price:.2f} "
            f"(slippage: {actual_slippage:.1f}bps, venue: {routing_decision.venue})"
        )
        
        return result
    
    def _simulate_execution(
        self,
        request: ExecutionRequest,
        routing_decision: RoutingDecision,
        estimated_slippage_bps: float
    ) -> tuple[float, float]:
        """
        Simulate order execution.
        
        Returns:
            (fill_price, quantity_filled)
        """
        # Simulate slippage (add some randomness)
        import random
        actual_slippage_bps = estimated_slippage_bps * random.uniform(0.8, 1.2)
        
        # Calculate fill price
        slippage_fraction = actual_slippage_bps / 10000
        if request.side == "buy":
            fill_price = request.current_price * (1 + slippage_fraction)
        else:
            fill_price = request.current_price * (1 - slippage_fraction)
        
        # Simulate fill rate (most orders fill completely)
        if routing_decision.order_type == "market":
            fill_rate = 1.0
        elif routing_decision.order_type == "limit":
            # Limit orders have some chance of partial fill
            fill_rate = random.uniform(0.95, 1.0)
        else:
            fill_rate = random.uniform(0.90, 1.0)
        
        quantity_filled = request.quantity * fill_rate
        
        return fill_price, quantity_filled
    
    def _calculate_fill_quality(
        self,
        fill_rate: float,
        slippage_bps: float,
        execution_time: float
    ) -> float:
        """
        Calculate overall fill quality score (0-1).
        
        Components:
        - Fill rate (40%)
        - Slippage (40%)
        - Execution time (20%)
        """
        # Fill rate score
        fill_score = fill_rate
        
        # Slippage score (inverted, 0 bps = 1.0, 50 bps = 0.0)
        slippage_score = max(0.0, 1.0 - abs(slippage_bps) / 50.0)
        
        # Time score (inverted, 0s = 1.0, 60s = 0.0)
        time_score = max(0.0, 1.0 - execution_time / 60.0)
        
        quality = 0.40 * fill_score + 0.40 * slippage_score + 0.20 * time_score
        return quality
    
    def _adapt_parameters(
        self,
        actual_slippage: float,
        volatility: float,
        order_size_ratio: float
    ):
        """
        Adapt routing parameters based on execution feedback.
        
        If slippage is consistently high:
        - Increase volatility threshold (be more conservative)
        - Decrease liquidity threshold (split orders earlier)
        """
        # Get recent slippage stats
        recent_stats = self.quality_tracker.get_recent_slippage_stats(lookback_minutes=60)
        
        if recent_stats["count"] < 10:
            return  # Not enough data
        
        avg_slippage = recent_stats["avg_slippage_bps"]
        
        # If average slippage is high, be more conservative
        if avg_slippage > 20.0:  # 20 bps threshold
            # Increase volatility threshold (trigger high-vol routing earlier)
            adjustment = self.learning_rate * 0.005  # 0.5% adjustment
            self.adaptive_volatility_threshold = min(
                self.adaptive_volatility_threshold + adjustment,
                0.05  # Max 5%
            )
            
            # Decrease liquidity threshold (split orders earlier)
            adjustment = self.learning_rate * 0.001  # 0.1% adjustment
            self.adaptive_liquidity_threshold = max(
                self.adaptive_liquidity_threshold - adjustment,
                0.005  # Min 0.5%
            )
            
            logger.info(
                f"Adapted parameters: vol_threshold={self.adaptive_volatility_threshold:.4f}, "
                f"liq_threshold={self.adaptive_liquidity_threshold:.4f} "
                f"(avg_slippage={avg_slippage:.1f}bps)"
            )
            
            # Update router thresholds
            self.router.volatility_threshold_high = self.adaptive_volatility_threshold
            self.router.liquidity_threshold_low = self.adaptive_liquidity_threshold
        
        # If average slippage is low, can be more aggressive
        elif avg_slippage < 5.0:  # 5 bps threshold
            # Decrease volatility threshold (less conservative)
            adjustment = self.learning_rate * 0.002
            self.adaptive_volatility_threshold = max(
                self.adaptive_volatility_threshold - adjustment,
                0.02  # Min 2%
            )
            
            # Increase liquidity threshold (split less often)
            adjustment = self.learning_rate * 0.0005
            self.adaptive_liquidity_threshold = min(
                self.adaptive_liquidity_threshold + adjustment,
                0.02  # Max 2%
            )
            
            logger.debug(
                f"Adapted parameters: vol_threshold={self.adaptive_volatility_threshold:.4f}, "
                f"liq_threshold={self.adaptive_liquidity_threshold:.4f} "
                f"(avg_slippage={avg_slippage:.1f}bps)"
            )
            
            # Update router thresholds
            self.router.volatility_threshold_high = self.adaptive_volatility_threshold
            self.router.liquidity_threshold_low = self.adaptive_liquidity_threshold
    
    def get_execution_stats(self) -> Dict:
        """Get comprehensive execution statistics"""
        quality_summary = self.quality_tracker.get_execution_summary()
        routing_stats = self.router.get_routing_stats()
        recent_slippage = self.quality_tracker.get_recent_slippage_stats(lookback_minutes=60)
        recent_fills = self.quality_tracker.get_fill_rate_stats(lookback_minutes=60)
        
        return {
            "market": self.market,
            "adaptive_learning_enabled": self.enable_adaptive_learning,
            "adaptive_parameters": {
                "volatility_threshold": self.adaptive_volatility_threshold,
                "liquidity_threshold": self.adaptive_liquidity_threshold
            },
            "quality_summary": quality_summary,
            "routing_stats": routing_stats,
            "recent_slippage": recent_slippage,
            "recent_fills": recent_fills
        }
    
    def reset_adaptive_parameters(self):
        """Reset adaptive parameters to defaults"""
        self.adaptive_volatility_threshold = 0.03
        self.adaptive_liquidity_threshold = 0.01
        self.router.volatility_threshold_high = 0.03
        self.router.liquidity_threshold_low = 0.01
        logger.info("Reset adaptive parameters to defaults")
