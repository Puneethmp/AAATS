"""
Execution Module — Intelligent Order Execution

Provides:
- Smart order routing based on market conditions
- Execution quality tracking and analysis
- Adaptive execution engine with learning
- Integration with paper trading and live execution

Phase 8: Execution Intelligence
"""

from execution.smart_order_router import (
    SmartOrderRouter,
    OrderUrgency,
    RoutingDecision,
    VenueType
)

from execution.execution_quality_tracker import (
    ExecutionQualityTracker,
    ExecutionRecord,
    VenueQualityMetrics
)

from execution.adaptive_execution_engine import (
    AdaptiveExecutionEngine,
    ExecutionRequest,
    ExecutionResult
)

__all__ = [
    # Smart Order Router
    "SmartOrderRouter",
    "OrderUrgency",
    "RoutingDecision",
    "VenueType",
    
    # Execution Quality Tracker
    "ExecutionQualityTracker",
    "ExecutionRecord",
    "VenueQualityMetrics",
    
    # Adaptive Execution Engine
    "AdaptiveExecutionEngine",
    "ExecutionRequest",
    "ExecutionResult",
]
