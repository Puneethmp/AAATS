"""
Smart Order Router — Execution Intelligence Layer

Intelligently routes orders based on:
- Market conditions (volatility, liquidity)
- Order size vs market depth
- Time of day (market hours, session transitions)
- Historical fill quality
- Venue selection (for crypto multi-exchange)

Part of Phase 8: Execution Intelligence
"""

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class OrderUrgency(Enum):
    """Order urgency classification"""
    IMMEDIATE = "immediate"  # Market order, fill now
    NORMAL = "normal"        # Standard limit order
    PATIENT = "patient"      # Can wait for better price


class VenueType(Enum):
    """Execution venue types"""
    PRIMARY = "primary"      # Main exchange (Alpaca, Angel One, Binance)
    BACKUP = "backup"        # Backup exchange
    DARK_POOL = "dark_pool"  # Dark pool (future)


@dataclass
class RoutingDecision:
    """Order routing decision"""
    venue: str
    order_type: str  # "market", "limit", "iceberg"
    urgency: OrderUrgency
    split_order: bool
    num_chunks: int
    time_spacing_seconds: int
    limit_price: Optional[float]
    reason: str
    confidence: float


class SmartOrderRouter:
    """
    Intelligent order routing based on market conditions.
    
    Routes orders to optimal execution venue with appropriate
    order type, sizing, and timing based on:
    - Market volatility
    - Order size vs liquidity
    - Time of day
    - Historical fill quality
    """
    
    def __init__(
        self,
        market: str,
        volatility_threshold_high: float = 0.03,  # 3% volatility = high
        liquidity_threshold_low: float = 0.01,    # Order > 1% ADV = large
        iceberg_size_threshold: float = 0.005     # Order > 0.5% ADV = iceberg
    ):
        """
        Initialize smart order router.
        
        Args:
            market: Market identifier ("us", "india", "crypto")
            volatility_threshold_high: Volatility above this = high vol
            liquidity_threshold_low: Order size ratio triggering special handling
            iceberg_size_threshold: Order size ratio triggering iceberg orders
        """
        self.market = market
        self.volatility_threshold_high = volatility_threshold_high
        self.liquidity_threshold_low = liquidity_threshold_low
        self.iceberg_size_threshold = iceberg_size_threshold
        
        # Venue fill quality tracking (updated by execution feedback)
        self.venue_fill_quality: Dict[str, float] = {}
        
        logger.info(
            f"SmartOrderRouter initialized for {market}: "
            f"vol_threshold={volatility_threshold_high}, "
            f"liquidity_threshold={liquidity_threshold_low}"
        )
    
    def route_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_price: float,
        volatility: float,
        avg_daily_volume: float,
        time_of_day: datetime,
        urgency: OrderUrgency = OrderUrgency.NORMAL
    ) -> RoutingDecision:
        """
        Determine optimal routing for an order.
        
        Args:
            symbol: Trading symbol
            side: "buy" or "sell"
            quantity: Order quantity
            current_price: Current market price
            volatility: Current volatility (e.g., ATR / price)
            avg_daily_volume: Average daily volume
            time_of_day: Current time
            urgency: Order urgency level
        
        Returns:
            RoutingDecision with venue, order type, and execution parameters
        """
        # Calculate order size as fraction of daily volume
        order_value = quantity * current_price
        daily_value = avg_daily_volume * current_price
        order_size_ratio = order_value / daily_value if daily_value > 0 else 1.0
        
        # Determine if high volatility
        is_high_vol = volatility > self.volatility_threshold_high
        
        # Determine if large order
        is_large_order = order_size_ratio > self.liquidity_threshold_low
        
        # Determine if market hours (affects liquidity)
        is_market_hours = self._is_market_hours(time_of_day)
        
        # Route based on conditions
        if urgency == OrderUrgency.IMMEDIATE:
            return self._route_immediate(
                symbol, side, quantity, current_price, is_high_vol
            )
        
        elif is_large_order:
            return self._route_large_order(
                symbol, side, quantity, current_price, order_size_ratio,
                is_high_vol, is_market_hours
            )
        
        elif is_high_vol:
            return self._route_high_volatility(
                symbol, side, quantity, current_price, is_market_hours
            )
        
        else:
            return self._route_normal(
                symbol, side, quantity, current_price, is_market_hours
            )
    
    def _route_immediate(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_price: float,
        is_high_vol: bool
    ) -> RoutingDecision:
        """Route immediate urgency orders (market orders)"""
        venue = self._select_best_venue()
        
        # Use market order for immediate execution
        # In high vol, add a limit collar to prevent extreme slippage
        if is_high_vol:
            # Limit collar: ±2% from current price
            collar_pct = 0.02
            limit_price = (
                current_price * (1 + collar_pct) if side == "buy"
                else current_price * (1 - collar_pct)
            )
            order_type = "limit"
            reason = "Immediate execution with limit collar (high volatility)"
        else:
            limit_price = None
            order_type = "market"
            reason = "Immediate market order"
        
        return RoutingDecision(
            venue=venue,
            order_type=order_type,
            urgency=OrderUrgency.IMMEDIATE,
            split_order=False,
            num_chunks=1,
            time_spacing_seconds=0,
            limit_price=limit_price,
            reason=reason,
            confidence=0.95
        )
    
    def _route_large_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_price: float,
        order_size_ratio: float,
        is_high_vol: bool,
        is_market_hours: bool
    ) -> RoutingDecision:
        """Route large orders (split into chunks or iceberg)"""
        venue = self._select_best_venue()
        
        # Very large orders: split into time-spaced chunks
        if order_size_ratio > self.liquidity_threshold_low:
            num_chunks = min(int(order_size_ratio / 0.005) + 1, 10)  # Max 10 chunks
            time_spacing = 60 if is_market_hours else 300  # 1 min or 5 min
            
            # Use limit orders for chunks
            limit_offset = 0.001 if not is_high_vol else 0.002  # 0.1% or 0.2%
            limit_price = (
                current_price * (1 + limit_offset) if side == "buy"
                else current_price * (1 - limit_offset)
            )
            
            return RoutingDecision(
                venue=venue,
                order_type="limit",
                urgency=OrderUrgency.PATIENT,
                split_order=True,
                num_chunks=num_chunks,
                time_spacing_seconds=time_spacing,
                limit_price=limit_price,
                reason=f"Large order split into {num_chunks} chunks to minimize impact",
                confidence=0.85
            )
        
        # Medium-large orders: use iceberg order
        elif order_size_ratio > self.iceberg_size_threshold:
            limit_offset = 0.0005 if not is_high_vol else 0.001
            limit_price = (
                current_price * (1 + limit_offset) if side == "buy"
                else current_price * (1 - limit_offset)
            )
            
            return RoutingDecision(
                venue=venue,
                order_type="iceberg",
                urgency=OrderUrgency.NORMAL,
                split_order=False,
                num_chunks=1,
                time_spacing_seconds=0,
                limit_price=limit_price,
                reason="Iceberg order to hide size",
                confidence=0.90
            )
        
        else:
            # Standard limit order
            return self._route_normal(symbol, side, quantity, current_price, is_market_hours)
    
    def _route_high_volatility(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_price: float,
        is_market_hours: bool
    ) -> RoutingDecision:
        """Route orders during high volatility"""
        venue = self._select_best_venue()
        
        # Use limit orders with wider spread in high vol
        limit_offset = 0.002  # 0.2% from current price
        limit_price = (
            current_price * (1 + limit_offset) if side == "buy"
            else current_price * (1 - limit_offset)
        )
        
        return RoutingDecision(
            venue=venue,
            order_type="limit",
            urgency=OrderUrgency.NORMAL,
            split_order=False,
            num_chunks=1,
            time_spacing_seconds=0,
            limit_price=limit_price,
            reason="Limit order with wider spread (high volatility)",
            confidence=0.80
        )
    
    def _route_normal(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_price: float,
        is_market_hours: bool
    ) -> RoutingDecision:
        """Route normal orders (standard conditions)"""
        venue = self._select_best_venue()
        
        # Standard limit order with tight spread
        limit_offset = 0.0005  # 0.05% from current price
        limit_price = (
            current_price * (1 + limit_offset) if side == "buy"
            else current_price * (1 - limit_offset)
        )
        
        return RoutingDecision(
            venue=venue,
            order_type="limit",
            urgency=OrderUrgency.NORMAL,
            split_order=False,
            num_chunks=1,
            time_spacing_seconds=0,
            limit_price=limit_price,
            reason="Standard limit order (normal conditions)",
            confidence=0.90
        )
    
    def _select_best_venue(self) -> str:
        """Select best execution venue based on fill quality"""
        if not self.venue_fill_quality:
            # Default venues by market
            default_venues = {
                "us": "alpaca",
                "india": "angel_one",
                "crypto": "binance"
            }
            return default_venues.get(self.market, "primary")
        
        # Select venue with best fill quality
        best_venue = max(self.venue_fill_quality.items(), key=lambda x: x[1])[0]
        return best_venue
    
    def _is_market_hours(self, time_of_day: datetime) -> bool:
        """Check if within market hours"""
        hour = time_of_day.hour
        minute = time_of_day.minute
        
        if self.market == "us":
            # US: 9:30 AM - 4:00 PM ET (14:30 - 21:00 UTC)
            # Simplified: 9:00 - 16:00 local
            return 9 <= hour < 16
        
        elif self.market == "india":
            # India: 9:15 AM - 3:30 PM IST
            return (hour == 9 and minute >= 15) or (10 <= hour < 15) or (hour == 15 and minute <= 30)
        
        elif self.market == "crypto":
            # Crypto: 24/7, but liquidity varies
            # Consider 8 AM - 8 PM as "high liquidity hours"
            return 8 <= hour < 20
        
        return True
    
    def update_venue_quality(self, venue: str, fill_quality: float):
        """
        Update venue fill quality based on execution feedback.
        
        Args:
            venue: Venue identifier
            fill_quality: Quality score 0.0-1.0 (1.0 = best)
        """
        if venue not in self.venue_fill_quality:
            self.venue_fill_quality[venue] = fill_quality
        else:
            # Exponential moving average
            alpha = 0.2
            self.venue_fill_quality[venue] = (
                alpha * fill_quality + (1 - alpha) * self.venue_fill_quality[venue]
            )
        
        logger.debug(f"Updated {venue} fill quality: {self.venue_fill_quality[venue]:.3f}")
    
    def get_routing_stats(self) -> Dict:
        """Get routing statistics"""
        return {
            "market": self.market,
            "venue_quality": dict(self.venue_fill_quality),
            "volatility_threshold": self.volatility_threshold_high,
            "liquidity_threshold": self.liquidity_threshold_low
        }
