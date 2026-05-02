"""
Tests for PerformanceTracker

Validates:
- Trade recording and retrieval
- Strategy performance aggregation
- Market performance calculation
- Sharpe ratio calculations
- Drawdown tracking
- Performance trend detection
"""

import pytest
import time
from pathlib import Path
import tempfile
import shutil

from learning.performance_tracker import (
    PerformanceTracker,
    TradePerformance,
    StrategyPerformance,
    MarketPerformance,
)


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "test_performance.db"
    yield db_path
    # Close any open connections before cleanup
    import gc
    gc.collect()
    try:
        shutil.rmtree(temp_dir)
    except PermissionError:
        pass  # Windows file locking issue - ignore


@pytest.fixture
def tracker(temp_db):
    """Create PerformanceTracker with temporary database"""
    tracker_inst = PerformanceTracker(db_path=temp_db)
    yield tracker_inst
    # Ensure connections are closed
    del tracker_inst
    import gc
    gc.collect()


def create_trade(
    trade_id: str,
    strategy_id: str = "test_strategy",
    market: str = "crypto",
    pnl: float = 100.0,
    win: bool = True,
    **kwargs
) -> TradePerformance:
    """Helper to create TradePerformance"""
    now = time.time()
    return TradePerformance(
        trade_id=trade_id,
        strategy_id=strategy_id,
        market=market,
        symbol=kwargs.get("symbol", "BTC/USD"),
        entry_time=now - 3600,
        exit_time=now,
        entry_price=kwargs.get("entry_price", 50000.0),
        exit_price=kwargs.get("exit_price", 50100.0),
        quantity=kwargs.get("quantity", 0.1),
        pnl=pnl,
        pnl_percent=kwargs.get("pnl_percent", pnl / 5000.0),
        holding_period_hours=kwargs.get("holding_period_hours", 1.0),
        regime=kwargs.get("regime", "bull"),
        signal_confidence=kwargs.get("signal_confidence", 0.75),
        win=win,
        slippage_bps=kwargs.get("slippage_bps", 5.0),
        commission=kwargs.get("commission", 2.0),
    )


class TestTradeRecording:
    """Test trade recording functionality"""
    
    def test_record_single_trade(self, tracker):
        """Test recording a single trade"""
        trade = create_trade("trade_001", pnl=100.0, win=True)
        tracker.record_trade(trade)
        
        # Verify trade was recorded
        outcomes = tracker.get_recent_outcomes("test_strategy", "crypto", count=10)
        assert len(outcomes) == 1
        assert outcomes[0] is True
    
    def test_record_multiple_trades(self, tracker):
        """Test recording multiple trades"""
        trades = [
            create_trade(f"trade_{i:03d}", pnl=100.0 if i % 2 == 0 else -50.0, win=i % 2 == 0)
            for i in range(10)
        ]
        
        for trade in trades:
            tracker.record_trade(trade)
        
        outcomes = tracker.get_recent_outcomes("test_strategy", "crypto", count=20)
        assert len(outcomes) == 10
        assert sum(outcomes) == 5  # 5 wins
    
    def test_record_different_strategies(self, tracker):
        """Test recording trades for different strategies"""
        trade1 = create_trade("trade_001", strategy_id="strategy_a", pnl=100.0, win=True)
        trade2 = create_trade("trade_002", strategy_id="strategy_b", pnl=-50.0, win=False)
        
        tracker.record_trade(trade1)
        tracker.record_trade(trade2)
        
        outcomes_a = tracker.get_recent_outcomes("strategy_a", "crypto", count=10)
        outcomes_b = tracker.get_recent_outcomes("strategy_b", "crypto", count=10)
        
        assert len(outcomes_a) == 1
        assert len(outcomes_b) == 1
        assert outcomes_a[0] is True
        assert outcomes_b[0] is False


class TestStrategyPerformance:
    """Test strategy performance aggregation"""
    
    def test_strategy_performance_basic(self, tracker):
        """Test basic strategy performance calculation"""
        # Record 10 trades: 6 wins, 4 losses
        for i in range(10):
            win = i < 6
            pnl = 100.0 if win else -50.0
            trade = create_trade(f"trade_{i:03d}", pnl=pnl, win=win, pnl_percent=pnl/5000.0)
            tracker.record_trade(trade)
        
        perf = tracker.get_strategy_performance("test_strategy", "crypto", lookback_days=1)
        
        assert perf is not None
        assert perf.total_trades == 10
        assert perf.winning_trades == 6
        assert perf.losing_trades == 4
        assert perf.win_rate == 0.6
        assert perf.total_pnl == 400.0  # 6*100 - 4*50
    
    def test_strategy_performance_sharpe(self, tracker):
        """Test Sharpe ratio calculation"""
        # Record trades with varying returns
        returns = [0.02, 0.01, -0.01, 0.03, 0.02, -0.005, 0.015, 0.01, 0.02, 0.01]
        
        for i, ret in enumerate(returns):
            pnl = ret * 5000.0
            trade = create_trade(
                f"trade_{i:03d}",
                pnl=pnl,
                win=pnl > 0,
                pnl_percent=ret
            )
            tracker.record_trade(trade)
        
        perf = tracker.get_strategy_performance("test_strategy", "crypto", lookback_days=1)
        
        assert perf is not None
        assert perf.sharpe_ratio > 0  # Should be positive with mostly positive returns
    
    def test_strategy_performance_profit_factor(self, tracker):
        """Test profit factor calculation"""
        # 3 wins of 100, 2 losses of 50
        for i in range(5):
            win = i < 3
            pnl = 100.0 if win else -50.0
            trade = create_trade(f"trade_{i:03d}", pnl=pnl, win=win)
            tracker.record_trade(trade)
        
        perf = tracker.get_strategy_performance("test_strategy", "crypto", lookback_days=1)
        
        assert perf is not None
        assert perf.profit_factor == 3.0  # 300 / 100
    
    def test_strategy_performance_drawdown(self, tracker):
        """Test drawdown calculation"""
        # Create trades that result in drawdown
        pnls = [100, 100, -50, -50, -50, 100, 100]  # Peak at 200, drawdown to 50
        
        for i, pnl in enumerate(pnls):
            trade = create_trade(f"trade_{i:03d}", pnl=pnl, win=pnl > 0)
            tracker.record_trade(trade)
        
        perf = tracker.get_strategy_performance("test_strategy", "crypto", lookback_days=1)
        
        assert perf is not None
        assert perf.max_drawdown < 0  # Should have negative drawdown
    
    def test_strategy_performance_trend(self, tracker):
        """Test performance trend detection"""
        # First half: poor performance, second half: good performance
        for i in range(20):
            if i < 10:
                # First half: 40% win rate
                win = i < 4
                pnl = 50.0 if win else -50.0
            else:
                # Second half: 80% win rate
                win = (i - 10) < 8
                pnl = 100.0 if win else -50.0
            
            trade = create_trade(f"trade_{i:03d}", pnl=pnl, win=win, pnl_percent=pnl/5000.0)
            tracker.record_trade(trade)
        
        perf = tracker.get_strategy_performance("test_strategy", "crypto", lookback_days=1)
        
        assert perf is not None
        assert perf.performance_trend == "improving"
    
    def test_no_trades_returns_none(self, tracker):
        """Test that no trades returns None"""
        perf = tracker.get_strategy_performance("nonexistent", "crypto", lookback_days=1)
        assert perf is None


class TestMarketPerformance:
    """Test market-level performance aggregation"""
    
    def test_market_performance_basic(self, tracker):
        """Test basic market performance calculation"""
        # Record trades for multiple strategies in same market
        for strategy_id in ["strategy_a", "strategy_b"]:
            for i in range(5):
                win = i < 3
                pnl = 100.0 if win else -50.0
                trade = create_trade(
                    f"{strategy_id}_trade_{i:03d}",
                    strategy_id=strategy_id,
                    pnl=pnl,
                    win=win,
                    pnl_percent=pnl/5000.0
                )
                tracker.record_trade(trade)
        
        market_perf = tracker.get_market_performance("crypto", lookback_days=1)
        
        assert market_perf is not None
        assert market_perf.total_trades == 10
        assert market_perf.active_strategies == 2
        # Each strategy: 3 wins of 100, 2 losses of 50 = 200 per strategy = 400 total
        assert market_perf.total_pnl == 400.0  # 2 * (3*100 - 2*50)
    
    def test_market_performance_strategy_ranking(self, tracker):
        """Test strategy ranking within market"""
        # Strategy A: profitable
        for i in range(5):
            trade = create_trade(f"a_trade_{i:03d}", strategy_id="strategy_a", pnl=100.0, win=True)
            tracker.record_trade(trade)
        
        # Strategy B: unprofitable
        for i in range(5):
            trade = create_trade(f"b_trade_{i:03d}", strategy_id="strategy_b", pnl=-50.0, win=False)
            tracker.record_trade(trade)
        
        market_perf = tracker.get_market_performance("crypto", lookback_days=1)
        
        assert market_perf is not None
        assert market_perf.best_strategy == "strategy_a"
        assert market_perf.worst_strategy == "strategy_b"
    
    def test_no_market_trades_returns_none(self, tracker):
        """Test that no market trades returns None"""
        market_perf = tracker.get_market_performance("nonexistent", lookback_days=1)
        assert market_perf is None


class TestPerformanceSnapshot:
    """Test performance snapshot functionality"""
    
    def test_snapshot_creation(self, tracker):
        """Test creating performance snapshot"""
        # Record some trades
        for i in range(5):
            trade = create_trade(f"trade_{i:03d}", pnl=100.0, win=True)
            tracker.record_trade(trade)
        
        # Create snapshot
        tracker.snapshot_strategy("test_strategy", "crypto", lookback_days=1)
        
        # Verify snapshot was created (no exception means success)
        assert True
    
    def test_snapshot_no_trades(self, tracker):
        """Test snapshot with no trades (should not fail)"""
        tracker.snapshot_strategy("nonexistent", "crypto", lookback_days=1)
        assert True


class TestUtilityMethods:
    """Test utility methods"""
    
    def test_get_all_strategies(self, tracker):
        """Test getting all strategies"""
        # Record trades for multiple strategies
        for strategy_id in ["strategy_a", "strategy_b", "strategy_c"]:
            trade = create_trade(f"{strategy_id}_trade", strategy_id=strategy_id)
            tracker.record_trade(trade)
        
        strategies = tracker.get_all_strategies()
        assert len(strategies) == 3
        assert "strategy_a" in strategies
        assert "strategy_b" in strategies
        assert "strategy_c" in strategies
    
    def test_get_all_strategies_filtered_by_market(self, tracker):
        """Test getting strategies filtered by market"""
        # Record trades in different markets
        trade1 = create_trade("trade_001", strategy_id="strategy_a", market="crypto")
        trade2 = create_trade("trade_002", strategy_id="strategy_b", market="india")
        
        tracker.record_trade(trade1)
        tracker.record_trade(trade2)
        
        crypto_strategies = tracker.get_all_strategies(market="crypto")
        india_strategies = tracker.get_all_strategies(market="india")
        
        assert len(crypto_strategies) == 1
        assert len(india_strategies) == 1
        assert "strategy_a" in crypto_strategies
        assert "strategy_b" in india_strategies
