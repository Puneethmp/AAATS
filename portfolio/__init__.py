"""
Portfolio Intelligence Layer

Adaptive capital allocation and portfolio risk management across strategies.

Modules:
- capital_allocator: Adaptive capital allocation based on strategy performance
- exposure_balancer: Cross-strategy exposure balancing
- correlation_monitor: Strategy correlation tracking and clustering
- volatility_targeting: Portfolio volatility targeting
- drawdown_allocator: Drawdown-aware capital allocation
- position_sizer: Adaptive position sizing
- capital_throttle: Capital throttling during high volatility
- regime_allocator: Regime-aware allocation
- strategy_health: Strategy health scoring
- risk_aggregator: Portfolio risk aggregation
"""

from portfolio.capital_allocator import CapitalAllocator
from portfolio.exposure_balancer import ExposureBalancer
from portfolio.correlation_monitor import CorrelationMonitor
from portfolio.volatility_targeting import VolatilityTargeting
from portfolio.drawdown_allocator import DrawdownAllocator
from portfolio.position_sizer import AdaptivePositionSizer
from portfolio.capital_throttle import CapitalThrottle
from portfolio.regime_allocator import RegimeAllocator
from portfolio.strategy_health import StrategyHealthScorer
from portfolio.risk_aggregator import RiskAggregator

__all__ = [
    "CapitalAllocator",
    "ExposureBalancer",
    "CorrelationMonitor",
    "VolatilityTargeting",
    "DrawdownAllocator",
    "AdaptivePositionSizer",
    "CapitalThrottle",
    "RegimeAllocator",
    "StrategyHealthScorer",
    "RiskAggregator",
]
