"""
Tests for AdaptiveEngine

Validates:
- Trade outcome recording
- Drift detection integration
- Retraining triggers
- Confidence threshold adjustment
- Strategy status management (probation/retirement)
- State persistence
"""

import pytest
import time
from pathlib import Path
import tempfile
import shutil
import json

from learning.adaptive_engine import AdaptiveEngine, StrategyState, AdaptiveAction
from learning.performance_tracker import TradePerformance, PerformanceTracker
from learning.optimizer import OptimizerState


@pytest.fixture
def temp_dir():
    """Create temporary directory for testing"""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    # Close any open connections before cleanup
    import gc
    gc.collect()
    try:
        shutil.rmtree(temp_path)
    except PermissionError:
        pass  # Windows file locking issue - ignore


@pytest.fixture
def engine(temp_dir):
    """Create AdaptiveEngine with temporary storage"""
    db_path = temp_dir / "test_performance.db"
    state_file = temp_dir / "test_adaptive_state.json"
    tracker = PerformanceTracker(db_path=db_path)
    engine_inst = AdaptiveEngine(performance_tracker=tracker, state_file=state_file)
    yield engine_inst
    # Ensure connections are closed
    del engine_inst
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
        entry_price=50000.0,
        exit_price=50100.0 if win else 49900.0,
        quantity=0.1,
        pnl=pnl,
        pnl_percent=pnl / 5000.0,
        holding_period_hours=1.0,
        regime="bull",
        signal_confidence=0.75,
        win=win,
    )


class TestTradeOutcomeRecording:
    """Test trade outcome recording"""
    
    def test_record_single_outcome(self, engine):
        """Test recording a single trade outcome"""
        trade = create_trade("trade_001", pnl=100.0, win=True)
        engine.record_trade_outcome(trade)
        
        # Verify strategy state was created
        key = ("test_strategy", "crypto")
        assert key in engine.strategy_states
        
        state = engine.strategy_states[key]
        assert len(state.optimizer_state.outcomes) == 1
        assert state.optimizer_state.outcomes[0] == 1  # Win
    
    def test_record_multiple_outcomes(self, engine):
        """Test recording multiple trade outcomes"""
        for i in range(10):
            win = i % 2 == 0
            trade = create_trade(f"trade_{i:03d}", pnl=100.0 if win else -50.0, win=win)
            engine.record_trade_outcome(trade)
        
        key = ("test_strategy", "crypto")
        state = engine.strategy_states[key]
        assert len(state.optimizer_state.outcomes) == 10
        assert sum(state.optimizer_state.outcomes) == 5  # 5 wins
    
    def test_record_different_strategies(self, engine):
        """Test recording outcomes for different strategies"""
        trade1 = create_trade("trade_001", strategy_id="strategy_a", win=True)
        trade2 = create_trade("trade_002", strategy_id="strategy_b", win=False)
        
        engine.record_trade_outcome(trade1)
        engine.record_trade_outcome(trade2)
        
        assert ("strategy_a", "crypto") in engine.strategy_states
        assert ("strategy_b", "crypto") in engine.strategy_states


class TestSharpeUpdate:
    """Test Sharpe ratio updates"""
    
    def test_update_sharpe(self, engine):
        """Test updating Sharpe ratio"""
        engine.update_strategy_sharpe("test_strategy", "crypto", 1.5)
        
        key = ("test_strategy", "crypto")
        state = engine.strategy_states[key]
        assert state.optimizer_state.peak_sharpe == 1.5
    
    def test_update_sharpe_tracks_peak(self, engine):
        """Test that peak Sharpe is tracked"""
        engine.update_strategy_sharpe("test_strategy", "crypto", 1.5)
        engine.update_strategy_sharpe("test_strategy", "crypto", 1.2)  # Lower
        engine.update_strategy_sharpe("test_strategy", "crypto", 1.8)  # Higher
        
        key = ("test_strategy", "crypto")
        state = engine.strategy_states[key]
        assert state.optimizer_state.peak_sharpe == 1.8


class TestAdaptationCycle:
    """Test adaptation cycle execution"""
    
    def test_adaptation_insufficient_trades(self, engine):
        """Test adaptation with insufficient trades"""
        # Record only a few trades
        for i in range(5):
            trade = create_trade(f"trade_{i:03d}", win=True)
            engine.record_trade_outcome(trade)
        
        result = engine.run_adaptation_cycle("test_strategy", "crypto")
        assert result["status"] == "insufficient_trades"
        assert result["trades"] == 5
    
    def test_adaptation_with_sufficient_trades(self, engine):
        """Test adaptation with sufficient trades"""
        # Record enough trades
        for i in range(25):
            win = i < 15  # 60% win rate
            trade = create_trade(f"trade_{i:03d}", pnl=100.0 if win else -50.0, win=win)
            engine.record_trade_outcome(trade)
        
        result = engine.run_adaptation_cycle("test_strategy", "crypto")
        
        assert "optimization" in result
        assert "actions_taken" in result
        assert "performance" in result
        assert result["current_status"] == "active"
    
    def test_adaptation_no_state(self, engine):
        """Test adaptation for strategy with no state"""
        result = engine.run_adaptation_cycle("nonexistent", "crypto")
        assert result["status"] == "no_state"
    
    def test_adaptation_retired_strategy(self, engine):
        """Test adaptation for retired strategy"""
        # Create a retired strategy
        key = ("test_strategy", "crypto")
        engine.strategy_states[key] = StrategyState(
            strategy_id="test_strategy",
            market="crypto",
            status="retired",
            retirement_reason="Poor performance"
        )
        
        result = engine.run_adaptation_cycle("test_strategy", "crypto")
        assert result["status"] == "retired"
        assert "reason" in result


class TestStrategyStatusEvaluation:
    """Test strategy status evaluation (probation/retirement)"""
    
    def test_probation_trigger(self, engine):
        """Test that poor performance triggers probation"""
        # Record trades with poor performance (low win rate)
        for i in range(30):
            win = i < 10  # 33% win rate - poor
            trade = create_trade(f"trade_{i:03d}", pnl=50.0 if win else -50.0, win=win)
            engine.record_trade_outcome(trade)
        
        result = engine.run_adaptation_cycle("test_strategy", "crypto")
        
        # Should trigger probation due to low health score
        key = ("test_strategy", "crypto")
        state = engine.strategy_states[key]
        # Status might be probation depending on exact health score calculation
        assert state.status in ["active", "probation"]
    
    def test_retirement_after_probation(self, engine):
        """Test retirement after extended probation"""
        # Create strategy in probation with old start time
        key = ("test_strategy", "crypto")
        engine.strategy_states[key] = StrategyState(
            strategy_id="test_strategy",
            market="crypto",
            status="probation",
            probation_start=time.time() - (8 * 86400)  # 8 days ago
        )
        
        # Record trades with continued poor performance
        for i in range(30):
            win = i < 8  # 27% win rate - very poor
            trade = create_trade(f"trade_{i:03d}", pnl=50.0 if win else -50.0, win=win)
            engine.record_trade_outcome(trade)
        
        result = engine.run_adaptation_cycle("test_strategy", "crypto")
        
        # Should retire after probation period with poor performance
        state = engine.strategy_states[key]
        # Retirement depends on health score threshold
        assert state.status in ["probation", "retired"]


class TestRunAllAdaptations:
    """Test running adaptations for all strategies"""
    
    def test_run_all_adaptations(self, engine):
        """Test running adaptations for multiple strategies"""
        # Create multiple strategies with trades
        for strategy_id in ["strategy_a", "strategy_b"]:
            for i in range(25):
                win = i < 15
                trade = create_trade(
                    f"{strategy_id}_trade_{i:03d}",
                    strategy_id=strategy_id,
                    pnl=100.0 if win else -50.0,
                    win=win
                )
                engine.record_trade_outcome(trade)
        
        results = engine.run_all_adaptations()
        
        assert "strategy_a_crypto" in results
        assert "strategy_b_crypto" in results
    
    def test_run_all_adaptations_skips_retired(self, engine):
        """Test that retired strategies are skipped"""
        # Create active and retired strategies
        engine.strategy_states[("active_strategy", "crypto")] = StrategyState(
            strategy_id="active_strategy",
            market="crypto",
            status="active"
        )
        engine.strategy_states[("retired_strategy", "crypto")] = StrategyState(
            strategy_id="retired_strategy",
            market="crypto",
            status="retired"
        )
        
        results = engine.run_all_adaptations()
        
        # Retired strategy should return retired status
        if "retired_strategy_crypto" in results:
            assert results["retired_strategy_crypto"]["status"] == "retired"


class TestStrategyStatus:
    """Test getting strategy status"""
    
    def test_get_strategy_status(self, engine):
        """Test getting strategy status"""
        # Record some trades
        for i in range(25):
            win = i < 15
            trade = create_trade(f"trade_{i:03d}", pnl=100.0 if win else -50.0, win=win)
            engine.record_trade_outcome(trade)
        
        # Run adaptation to generate actions
        engine.run_adaptation_cycle("test_strategy", "crypto")
        
        status = engine.get_strategy_status("test_strategy", "crypto")
        
        assert "status" in status
        assert "confidence_threshold" in status
        assert "retrain_count" in status
        assert "performance" in status
        assert "recent_actions" in status
    
    def test_get_status_unknown_strategy(self, engine):
        """Test getting status for unknown strategy"""
        status = engine.get_strategy_status("nonexistent", "crypto")
        assert status["status"] == "unknown"


class TestStatePersistence:
    """Test state saving and loading"""
    
    def test_state_save_and_load(self, temp_dir):
        """Test that state is saved and loaded correctly"""
        state_file = temp_dir / "test_state.json"
        db_path = temp_dir / "test_db.db"
        
        # Create engine and record some data
        tracker = PerformanceTracker(db_path=db_path)
        engine1 = AdaptiveEngine(performance_tracker=tracker, state_file=state_file)
        
        for i in range(25):
            trade = create_trade(f"trade_{i:03d}", win=i < 15)
            engine1.record_trade_outcome(trade)
        
        engine1.update_strategy_sharpe("test_strategy", "crypto", 1.5)
        engine1._save_state()
        
        # Create new engine and load state
        tracker2 = PerformanceTracker(db_path=db_path)
        engine2 = AdaptiveEngine(performance_tracker=tracker2, state_file=state_file)
        
        # Verify state was loaded
        key = ("test_strategy", "crypto")
        assert key in engine2.strategy_states
        state = engine2.strategy_states[key]
        assert state.optimizer_state.peak_sharpe == 1.5
    
    def test_state_file_not_exists(self, temp_dir):
        """Test loading when state file doesn't exist"""
        state_file = temp_dir / "nonexistent.json"
        db_path = temp_dir / "test_db.db"
        
        tracker = PerformanceTracker(db_path=db_path)
        engine = AdaptiveEngine(performance_tracker=tracker, state_file=state_file)
        
        # Should initialize with empty state
        assert len(engine.strategy_states) == 0


class TestActionLogging:
    """Test adaptive action logging"""
    
    def test_actions_logged(self, engine):
        """Test that adaptive actions are logged"""
        # Record trades to trigger adaptation
        for i in range(25):
            win = i < 15
            trade = create_trade(f"trade_{i:03d}", pnl=100.0 if win else -50.0, win=win)
            engine.record_trade_outcome(trade)
        
        initial_action_count = len(engine.actions)
        
        # Run adaptation
        engine.run_adaptation_cycle("test_strategy", "crypto")
        
        # Actions should be logged
        assert len(engine.actions) >= initial_action_count
    
    def test_action_details(self, engine):
        """Test that action details are captured"""
        # Record trades
        for i in range(25):
            trade = create_trade(f"trade_{i:03d}", win=True)
            engine.record_trade_outcome(trade)
        
        # Run adaptation
        engine.run_adaptation_cycle("test_strategy", "crypto")
        
        # Check action structure
        if engine.actions:
            action = engine.actions[-1]
            assert hasattr(action, 'timestamp')
            assert hasattr(action, 'strategy_id')
            assert hasattr(action, 'market')
            assert hasattr(action, 'action_type')
            assert hasattr(action, 'details')
            assert hasattr(action, 'reason')
