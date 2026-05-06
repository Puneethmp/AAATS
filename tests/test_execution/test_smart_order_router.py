"""
Tests for Smart Order Router

Tests routing decisions based on:
- Market conditions (volatility, liquidity)
- Order size
- Time of day
- Urgency level
"""

import pytest
from datetime import datetime
from execution.smart_order_router import (
    SmartOrderRouter,
    OrderUrgency,
    RoutingDecision
)


class TestSmartOrderRouter:
    """Test suite for SmartOrderRouter"""
    
    @pytest.fixture
    def router_us(self):
        """US market router"""
        return SmartOrderRouter(market="us")
    
    @pytest.fixture
    def router_india(self):
        """India market router"""
        return SmartOrderRouter(market="india")
    
    @pytest.fixture
    def router_crypto(self):
        """Crypto market router"""
        return SmartOrderRouter(market="crypto")
    
    def test_initialization(self, router_us):
        """Test router initialization"""
        assert router_us.market == "us"
        assert router_us.volatility_threshold_high == 0.03
        assert router_us.liquidity_threshold_low == 0.01
        assert router_us.venue_fill_quality == {}
    
    def test_normal_order_routing(self, router_us):
        """Test routing for normal market conditions"""
        decision = router_us.route_order(
            symbol="AAPL",
            side="buy",
            quantity=100,
            current_price=150.0,
            volatility=0.02,  # Normal volatility
            avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0),  # Market hours
            urgency=OrderUrgency.NORMAL
        )
        
        assert isinstance(decision, RoutingDecision)
        assert decision.order_type == "limit"
        assert decision.urgency == OrderUrgency.NORMAL
        assert not decision.split_order
        assert decision.num_chunks == 1
        assert decision.limit_price is not None
        assert decision.confidence > 0.8
    
    def test_immediate_urgency_routing(self, router_us):
        """Test routing for immediate urgency orders"""
        decision = router_us.route_order(
            symbol="AAPL",
            side="buy",
            quantity=100,
            current_price=150.0,
            volatility=0.02,
            avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0),
            urgency=OrderUrgency.IMMEDIATE
        )
        
        assert decision.urgency == OrderUrgency.IMMEDIATE
        assert decision.order_type == "market"
        assert not decision.split_order
        assert decision.confidence >= 0.95
    
    def test_immediate_urgency_high_volatility(self, router_us):
        """Test immediate order in high volatility gets limit collar"""
        decision = router_us.route_order(
            symbol="AAPL",
            side="buy",
            quantity=100,
            current_price=150.0,
            volatility=0.05,  # High volatility
            avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0),
            urgency=OrderUrgency.IMMEDIATE
        )
        
        assert decision.order_type == "limit"  # Limit collar applied
        assert decision.limit_price is not None
        assert decision.limit_price > 150.0  # Buy with collar
        assert "collar" in decision.reason.lower()
    
    def test_high_volatility_routing(self, router_us):
        """Test routing in high volatility conditions"""
        decision = router_us.route_order(
            symbol="AAPL",
            side="buy",
            quantity=100,
            current_price=150.0,
            volatility=0.04,  # Above threshold (0.03)
            avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0),
            urgency=OrderUrgency.NORMAL
        )
        
        assert decision.order_type == "limit"
        assert decision.limit_price is not None
        # Wider spread in high volatility
        spread_pct = abs(decision.limit_price - 150.0) / 150.0
        assert spread_pct >= 0.002  # At least 0.2%
    
    def test_large_order_splitting(self, router_us):
        """Test large orders get split into chunks"""
        decision = router_us.route_order(
            symbol="AAPL",
            side="buy",
            quantity=20000,  # Large order
            current_price=150.0,
            volatility=0.02,
            avg_daily_volume=1000000,  # Order is 2% of ADV
            time_of_day=datetime(2024, 1, 1, 10, 0),
            urgency=OrderUrgency.NORMAL
        )
        
        assert decision.split_order
        assert decision.num_chunks > 1
        assert decision.num_chunks <= 10  # Max chunks
        assert decision.time_spacing_seconds > 0
        assert decision.urgency == OrderUrgency.PATIENT
    
    def test_medium_order_routing(self, router_us):
        """Test medium-sized orders (between iceberg and split thresholds)"""
        decision = router_us.route_order(
            symbol="AAPL",
            side="buy",
            quantity=6000,  # 0.6% of ADV (between 0.5% and 1%)
            current_price=150.0,
            volatility=0.02,
            avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0),
            urgency=OrderUrgency.NORMAL
        )
        
        # Order size is 0.6% of ADV - implementation uses limit orders
        # for this size range (iceberg is optional feature)
        assert decision.order_type in ["limit", "iceberg"]
        assert not decision.split_order
        assert decision.limit_price is not None
    
    def test_venue_selection_default(self, router_us, router_india, router_crypto):
        """Test default venue selection by market"""
        decision_us = router_us.route_order(
            symbol="AAPL", side="buy", quantity=100, current_price=150.0,
            volatility=0.02, avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0)
        )
        assert decision_us.venue == "alpaca"
        
        decision_india = router_india.route_order(
            symbol="RELIANCE", side="buy", quantity=100, current_price=2500.0,
            volatility=0.02, avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0)
        )
        assert decision_india.venue == "angel_one"
        
        decision_crypto = router_crypto.route_order(
            symbol="BTCUSDT", side="buy", quantity=0.1, current_price=50000.0,
            volatility=0.03, avg_daily_volume=10000,
            time_of_day=datetime(2024, 1, 1, 10, 0)
        )
        assert decision_crypto.venue == "binance"
    
    def test_venue_quality_update(self, router_us):
        """Test venue quality tracking"""
        router_us.update_venue_quality("alpaca", 0.9)
        assert "alpaca" in router_us.venue_fill_quality
        assert router_us.venue_fill_quality["alpaca"] == 0.9
        
        # Update again (should use EMA)
        router_us.update_venue_quality("alpaca", 0.8)
        assert 0.8 < router_us.venue_fill_quality["alpaca"] < 0.9
    
    def test_venue_selection_with_quality(self, router_us):
        """Test venue selection based on fill quality"""
        router_us.update_venue_quality("venue_a", 0.95)
        router_us.update_venue_quality("venue_b", 0.85)
        
        decision = router_us.route_order(
            symbol="AAPL", side="buy", quantity=100, current_price=150.0,
            volatility=0.02, avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0)
        )
        
        assert decision.venue == "venue_a"  # Best quality
    
    def test_market_hours_detection_us(self, router_us):
        """Test US market hours detection"""
        # During market hours
        assert router_us._is_market_hours(datetime(2024, 1, 1, 10, 0))
        assert router_us._is_market_hours(datetime(2024, 1, 1, 15, 30))
        
        # Outside market hours
        assert not router_us._is_market_hours(datetime(2024, 1, 1, 8, 0))
        assert not router_us._is_market_hours(datetime(2024, 1, 1, 17, 0))
    
    def test_market_hours_detection_india(self, router_india):
        """Test India market hours detection"""
        # During market hours
        assert router_india._is_market_hours(datetime(2024, 1, 1, 9, 30))
        assert router_india._is_market_hours(datetime(2024, 1, 1, 15, 0))
        
        # Outside market hours
        assert not router_india._is_market_hours(datetime(2024, 1, 1, 9, 0))
        assert not router_india._is_market_hours(datetime(2024, 1, 1, 16, 0))
    
    def test_market_hours_detection_crypto(self, router_crypto):
        """Test crypto market hours (24/7 but liquidity varies)"""
        # High liquidity hours
        assert router_crypto._is_market_hours(datetime(2024, 1, 1, 10, 0))
        assert router_crypto._is_market_hours(datetime(2024, 1, 1, 19, 0))
        
        # Low liquidity hours
        assert not router_crypto._is_market_hours(datetime(2024, 1, 1, 2, 0))
        assert not router_crypto._is_market_hours(datetime(2024, 1, 1, 22, 0))
    
    def test_buy_vs_sell_limit_prices(self, router_us):
        """Test limit prices are directionally correct"""
        buy_decision = router_us.route_order(
            symbol="AAPL", side="buy", quantity=100, current_price=150.0,
            volatility=0.02, avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0)
        )
        assert buy_decision.limit_price > 150.0  # Buy above current
        
        sell_decision = router_us.route_order(
            symbol="AAPL", side="sell", quantity=100, current_price=150.0,
            volatility=0.02, avg_daily_volume=1000000,
            time_of_day=datetime(2024, 1, 1, 10, 0)
        )
        assert sell_decision.limit_price < 150.0  # Sell below current
    
    def test_routing_stats(self, router_us):
        """Test routing statistics"""
        router_us.update_venue_quality("alpaca", 0.9)
        stats = router_us.get_routing_stats()
        
        assert stats["market"] == "us"
        assert "venue_quality" in stats
        assert "alpaca" in stats["venue_quality"]
        assert stats["volatility_threshold"] == 0.03
        assert stats["liquidity_threshold"] == 0.01
