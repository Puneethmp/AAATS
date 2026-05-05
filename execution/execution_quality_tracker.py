"""
Execution Quality Tracker — Execution Intelligence Layer

Tracks and analyzes execution quality metrics:
- Fill rate and partial fills
- Slippage (expected vs actual fill price) — measured as raw price delta
- Implementation Shortfall (IS) — measured via TCAAnalyzer (institutional standard)
- Time to fill
- Venue performance comparison
- Market impact estimation (square-root law via TCAAnalyzer)

Part of Phase 8: Execution Intelligence
TCA integration added: uses research.tca.TCAAnalyzer for proper IS decomposition.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import deque
import statistics
import logging

logger = logging.getLogger(__name__)

# TCA integration — lazy import to avoid circular deps at module load
try:
    from research.tca import TCAAnalyzer, Order as TCAOrder, TCAReport
    _TCA_AVAILABLE = True
    _tca_analyzer = TCAAnalyzer(impact_eta=0.1)
except ImportError:
    _TCA_AVAILABLE = False
    _tca_analyzer = None  # type: ignore[assignment]


@dataclass
class ExecutionRecord:
    """Single execution record"""
    order_id: str
    symbol: str
    side: str
    quantity_requested: float
    quantity_filled: float
    expected_price: float
    fill_price: float
    venue: str
    order_type: str
    timestamp_submitted: datetime
    timestamp_filled: Optional[datetime]
    market_volatility: float
    order_size_ratio: float  # Order size / ADV
    
    @property
    def fill_rate(self) -> float:
        """Percentage of order filled"""
        if self.quantity_requested == 0:
            return 0.0
        return self.quantity_filled / self.quantity_requested
    
    @property
    def slippage_bps(self) -> float:
        """Slippage in basis points (positive = worse than expected)"""
        if self.expected_price == 0:
            return 0.0
        
        if self.side == "buy":
            # Buy: positive slippage = paid more than expected
            slippage = (self.fill_price - self.expected_price) / self.expected_price
        else:
            # Sell: positive slippage = received less than expected
            slippage = (self.expected_price - self.fill_price) / self.expected_price
        
        return slippage * 10000  # Convert to basis points
    
    @property
    def time_to_fill_seconds(self) -> Optional[float]:
        """Time from submission to fill in seconds"""
        if self.timestamp_filled is None:
            return None
        return (self.timestamp_filled - self.timestamp_submitted).total_seconds()
    
    @property
    def is_complete_fill(self) -> bool:
        """Whether order was completely filled"""
        return self.fill_rate >= 0.99  # Allow 1% tolerance


@dataclass
class VenueQualityMetrics:
    """Aggregated quality metrics for a venue"""
    venue: str
    total_orders: int = 0
    complete_fills: int = 0
    avg_fill_rate: float = 0.0
    avg_slippage_bps: float = 0.0
    avg_time_to_fill: float = 0.0
    slippage_std: float = 0.0
    quality_score: float = 0.0  # 0-1, higher is better
    
    recent_slippages: deque = field(default_factory=lambda: deque(maxlen=100))
    recent_fill_rates: deque = field(default_factory=lambda: deque(maxlen=100))
    recent_times: deque = field(default_factory=lambda: deque(maxlen=100))


class ExecutionQualityTracker:
    """
    Tracks execution quality across all orders and venues.
    
    Provides:
    - Real-time execution quality metrics
    - Venue performance comparison
    - Slippage analysis
    - Fill rate tracking
    - Market impact estimation
    """
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize execution quality tracker.
        
        Args:
            max_history: Maximum number of execution records to keep
        """
        self.max_history = max_history
        self.execution_history: deque = deque(maxlen=max_history)
        self.venue_metrics: Dict[str, VenueQualityMetrics] = {}
        
        logger.info(f"ExecutionQualityTracker initialized with max_history={max_history}")
    
    def record_execution(
        self,
        order_id: str,
        symbol: str,
        side: str,
        quantity_requested: float,
        quantity_filled: float,
        expected_price: float,
        fill_price: float,
        venue: str,
        order_type: str,
        timestamp_submitted: datetime,
        timestamp_filled: Optional[datetime],
        market_volatility: float,
        order_size_ratio: float
    ):
        """
        Record a completed or partially filled order.
        
        Args:
            order_id: Unique order identifier
            symbol: Trading symbol
            side: "buy" or "sell"
            quantity_requested: Quantity requested
            quantity_filled: Quantity actually filled
            expected_price: Expected fill price (e.g., limit price or mid-market)
            fill_price: Actual fill price
            venue: Execution venue
            order_type: Order type ("market", "limit", etc.)
            timestamp_submitted: When order was submitted
            timestamp_filled: When order was filled (None if not filled)
            market_volatility: Market volatility at time of order
            order_size_ratio: Order size as fraction of daily volume
        """
        record = ExecutionRecord(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity_requested=quantity_requested,
            quantity_filled=quantity_filled,
            expected_price=expected_price,
            fill_price=fill_price,
            venue=venue,
            order_type=order_type,
            timestamp_submitted=timestamp_submitted,
            timestamp_filled=timestamp_filled,
            market_volatility=market_volatility,
            order_size_ratio=order_size_ratio
        )
        
        self.execution_history.append(record)
        self._update_venue_metrics(record)
        
        logger.debug(
            f"Recorded execution {order_id}: {symbol} {side} "
            f"fill_rate={record.fill_rate:.2%} slippage={record.slippage_bps:.1f}bps"
        )
    
    def _update_venue_metrics(self, record: ExecutionRecord):
        """Update aggregated metrics for a venue"""
        venue = record.venue
        
        if venue not in self.venue_metrics:
            self.venue_metrics[venue] = VenueQualityMetrics(venue=venue)
        
        metrics = self.venue_metrics[venue]
        metrics.total_orders += 1
        
        if record.is_complete_fill:
            metrics.complete_fills += 1
        
        # Update recent metrics
        metrics.recent_fill_rates.append(record.fill_rate)
        metrics.recent_slippages.append(record.slippage_bps)
        
        if record.time_to_fill_seconds is not None:
            metrics.recent_times.append(record.time_to_fill_seconds)
        
        # Recalculate aggregates
        if metrics.recent_fill_rates:
            metrics.avg_fill_rate = statistics.mean(metrics.recent_fill_rates)
        
        if metrics.recent_slippages:
            metrics.avg_slippage_bps = statistics.mean(metrics.recent_slippages)
            if len(metrics.recent_slippages) > 1:
                metrics.slippage_std = statistics.stdev(metrics.recent_slippages)
        
        if metrics.recent_times:
            metrics.avg_time_to_fill = statistics.mean(metrics.recent_times)
        
        # Calculate quality score (0-1, higher is better)
        metrics.quality_score = self._calculate_quality_score(metrics)
    
    def _calculate_quality_score(self, metrics: VenueQualityMetrics) -> float:
        """
        Calculate overall quality score for a venue.
        
        Score components:
        - Fill rate (40%): Higher is better
        - Slippage (40%): Lower is better
        - Time to fill (20%): Faster is better
        """
        if metrics.total_orders == 0:
            return 0.0
        
        # Fill rate score (0-1)
        fill_score = metrics.avg_fill_rate
        
        # Slippage score (0-1, inverted)
        # Assume 0 bps = 1.0, 50 bps = 0.0
        slippage_score = max(0.0, 1.0 - abs(metrics.avg_slippage_bps) / 50.0)
        
        # Time score (0-1, inverted)
        # Assume 0s = 1.0, 60s = 0.0
        time_score = max(0.0, 1.0 - metrics.avg_time_to_fill / 60.0) if metrics.avg_time_to_fill > 0 else 1.0
        
        # Weighted average
        quality_score = (
            0.40 * fill_score +
            0.40 * slippage_score +
            0.20 * time_score
        )
        
        return quality_score
    
    def get_venue_quality(self, venue: str) -> Optional[VenueQualityMetrics]:
        """Get quality metrics for a specific venue"""
        return self.venue_metrics.get(venue)
    
    def get_all_venue_metrics(self) -> Dict[str, VenueQualityMetrics]:
        """Get quality metrics for all venues"""
        return dict(self.venue_metrics)
    
    def get_best_venue(self) -> Optional[str]:
        """Get venue with highest quality score"""
        if not self.venue_metrics:
            return None
        
        best_venue = max(
            self.venue_metrics.items(),
            key=lambda x: x[1].quality_score
        )
        return best_venue[0]
    
    def get_recent_slippage_stats(self, lookback_minutes: int = 60) -> Dict:
        """
        Get slippage statistics for recent period.
        
        Args:
            lookback_minutes: How far back to look
        
        Returns:
            Dict with slippage statistics
        """
        cutoff_time = datetime.now() - timedelta(minutes=lookback_minutes)
        recent_records = [
            r for r in self.execution_history
            if r.timestamp_submitted >= cutoff_time
        ]
        
        if not recent_records:
            return {
                "count": 0,
                "avg_slippage_bps": 0.0,
                "median_slippage_bps": 0.0,
                "max_slippage_bps": 0.0,
                "std_slippage_bps": 0.0
            }
        
        slippages = [r.slippage_bps for r in recent_records]
        
        return {
            "count": len(slippages),
            "avg_slippage_bps": statistics.mean(slippages),
            "median_slippage_bps": statistics.median(slippages),
            "max_slippage_bps": max(slippages),
            "std_slippage_bps": statistics.stdev(slippages) if len(slippages) > 1 else 0.0
        }
    
    def get_fill_rate_stats(self, lookback_minutes: int = 60) -> Dict:
        """
        Get fill rate statistics for recent period.
        
        Args:
            lookback_minutes: How far back to look
        
        Returns:
            Dict with fill rate statistics
        """
        cutoff_time = datetime.now() - timedelta(minutes=lookback_minutes)
        recent_records = [
            r for r in self.execution_history
            if r.timestamp_submitted >= cutoff_time
        ]
        
        if not recent_records:
            return {
                "count": 0,
                "avg_fill_rate": 0.0,
                "complete_fills": 0,
                "partial_fills": 0,
                "complete_fill_rate": 0.0
            }
        
        complete_fills = sum(1 for r in recent_records if r.is_complete_fill)
        partial_fills = len(recent_records) - complete_fills
        
        return {
            "count": len(recent_records),
            "avg_fill_rate": statistics.mean([r.fill_rate for r in recent_records]),
            "complete_fills": complete_fills,
            "partial_fills": partial_fills,
            "complete_fill_rate": complete_fills / len(recent_records)
        }
    
    def estimate_market_impact(
        self,
        order_size_ratio: float,
        market_volatility: float
    ) -> float:
        """
        Estimate expected market impact for an order.
        
        Uses historical data to estimate slippage based on:
        - Order size relative to daily volume
        - Current market volatility
        
        Args:
            order_size_ratio: Order size / average daily volume
            market_volatility: Current market volatility
        
        Returns:
            Estimated slippage in basis points
        """
        # Find similar historical orders
        similar_orders = [
            r for r in self.execution_history
            if (
                abs(r.order_size_ratio - order_size_ratio) < 0.005 and
                abs(r.market_volatility - market_volatility) < 0.01
            )
        ]
        
        if similar_orders:
            # Use historical average
            return statistics.mean([r.slippage_bps for r in similar_orders])
        
        # Fallback: simple linear model
        # Base slippage + size impact + volatility impact
        base_slippage = 2.0  # 2 bps base
        size_impact = order_size_ratio * 1000  # 10 bps per 1% of ADV
        vol_impact = market_volatility * 100  # Scale with volatility
        
        return base_slippage + size_impact + vol_impact
    
    def get_execution_summary(self) -> Dict:
        """Get overall execution quality summary"""
        if not self.execution_history:
            return {
                "total_executions": 0,
                "avg_fill_rate": 0.0,
                "avg_slippage_bps": 0.0,
                "complete_fill_rate": 0.0,
                "venues": {}
            }

        all_records = list(self.execution_history)
        complete_fills = sum(1 for r in all_records if r.is_complete_fill)

        return {
            "total_executions": len(all_records),
        