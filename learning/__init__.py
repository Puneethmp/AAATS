"""
Learning & Adaptive Systems for AAATS

This module provides continuous learning and adaptation capabilities:
- Performance tracking and analysis
- Concept drift detection (ADWIN)
- Automatic retraining triggers
- Dynamic confidence threshold adjustment
- Strategy parameter optimization
- Strategy lifecycle management (probation/retirement)
"""

from learning.optimizer import (
    ADWINDetector,
    OptimizerState,
    DriftStatus,
    record_outcome,
    update_sharpe,
    should_retrain,
    adjust_confidence_threshold,
    run_optimization_cycle,
)

from learning.performance_tracker import (
    PerformanceTracker,
    TradePerformance,
    StrategyPerformance,
    MarketPerformance,
)

from learning.adaptive_engine import (
    AdaptiveEngine,
    StrategyState,
    AdaptiveAction,
)

__all__ = [
    # Optimizer components
    "ADWINDetector",
    "OptimizerState",
    "DriftStatus",
    "record_outcome",
    "update_sharpe",
    "should_retrain",
    "adjust_confidence_threshold",
    "run_optimization_cycle",
    # Performance tracking
    "PerformanceTracker",
    "TradePerformance",
    "StrategyPerformance",
    "MarketPerformance",
    # Adaptive engine
    "AdaptiveEngine",
    "StrategyState",
    "AdaptiveAction",
]
