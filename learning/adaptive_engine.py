"""
Adaptive Learning Engine for AAATS

Integrates all learning components into a unified adaptive system that:
- Monitors performance continuously
- Detects concept drift
- Triggers retraining when needed
- Adjusts confidence thresholds dynamically
- Optimizes strategy parameters
- Manages strategy lifecycle (promote/demote/retire)

This is the orchestrator for the entire learning loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from foundation.logger import get_logger
from learning.optimizer import (
    ADWINDetector,
    OptimizerState,
    record_outcome,
    run_optimization_cycle,
    update_sharpe,
)
from learning.performance_tracker import (
    PerformanceTracker,
    StrategyPerformance,
    TradePerformance,
)

_log = get_logger("learning", "adaptive_engine")


@dataclass
class StrategyState:
    """Tracks the adaptive state of a strategy"""
    strategy_id: str
    market: str
    optimizer_state: OptimizerState = field(default_factory=OptimizerState)
    last_optimization: float = 0.0
    last_snapshot: float = 0.0
    status: str = "active"  # active, probation, retired
    probation_start: Optional[float] = None
    retirement_reason: Optional[str] = None


@dataclass
class AdaptiveAction:
    """Represents an action taken by the adaptive engine"""
    timestamp: float
    strategy_id: str
    market: str
    action_type: str  # retrain, adjust_threshold, optimize_params, probation, retire
    details: Dict[str, Any]
    reason: str


class AdaptiveEngine:
    """
    Orchestrates the complete learning and adaptation loop.
    
    Responsibilities:
    - Track performance for all strategies
    - Detect drift and trigger retraining
    - Adjust confidence thresholds dynamically
    - Optimize strategy parameters periodically
    - Manage strategy lifecycle (probation, retirement)
    - Log all adaptive actions for audit trail
    """
    
    # Configuration
    OPTIMIZATION_INTERVAL_HOURS = 24  # Run optimization daily
    SNAPSHOT_INTERVAL_HOURS = 6  # Snapshot performance every 6 hours
    PROBATION_THRESHOLD_SCORE = 40.0  # Health score below this = probation
    RETIREMENT_THRESHOLD_SCORE = 25.0  # Health score below this = retire
    PROBATION_DURATION_DAYS = 7  # Days in probation before retirement
    MIN_TRADES_FOR_ADAPTATION = 20  # Minimum trades before adapting
    
    def __init__(
        self,
        performance_tracker: Optional[PerformanceTracker] = None,
        state_file: Path = Path("data/adaptive_state.json")
    ):
        """
        Initialize adaptive engine.
        
        Args:
            performance_tracker: PerformanceTracker instance (creates new if None)
            state_file: Path to save/load adaptive state
        """
        self.tracker = performance_tracker or PerformanceTracker()
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Strategy states indexed by (strategy_id, market)
        self.strategy_states: Dict[tuple[str, str], StrategyState] = {}
        
        # ADWIN detector (shared across strategies)
        self.drift_detector = ADWINDetector()
        
        # Action log
        self.actions: List[AdaptiveAction] = []
        
        self._load_state()
        _log.info("AdaptiveEngine initialized")
    
    def record_trade_outcome(
        self,
        trade: TradePerformance
    ) -> None:
        """
        Record a completed trade and update adaptive state.
        
        Args:
            trade: TradePerformance with complete trade details
        """
        # Record in performance tracker
        self.tracker.record_trade(trade)
        
        # Get or create strategy state
        key = (trade.strategy_id, trade.market)
        if key not in self.strategy_states:
            self.strategy_states[key] = StrategyState(
                strategy_id=trade.strategy_id,
                market=trade.market
            )
        
        state = self.strategy_states[key]
        
        # Update optimizer state with outcome
        record_outcome(state.optimizer_state, trade.win)
        
        _log.debug(
            f"Trade outcome recorded: {trade.strategy_id} | {trade.market} | "
            f"{'WIN' if trade.win else 'LOSS'}"
        )
    
    def update_strategy_sharpe(
        self,
        strategy_id: str,
        market: str,
        sharpe: float
    ) -> None:
        """
        Update Sharpe ratio for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            market: Market name
            sharpe: Current Sharpe ratio
        """
        key = (strategy_id, market)
        if key not in self.strategy_states:
            self.strategy_states[key] = StrategyState(
                strategy_id=strategy_id,
                market=market
            )
        
        state = self.strategy_states[key]
        update_sharpe(state.optimizer_state, sharpe)
    
    def run_adaptation_cycle(
        self,
        strategy_id: str,
        market: str
    ) -> Dict[str, Any]:
        """
        Run a complete adaptation cycle for a strategy.
        
        This includes:
        - Drift detection
        - Retraining decision
        - Threshold adjustment
        - Parameter optimization (if due)
        - Performance snapshot
        - Status evaluation (probation/retirement)
        
        Args:
            strategy_id: Strategy identifier
            market: Market name
            
        Returns:
            Dict with adaptation results and actions taken
        """
        key = (strategy_id, market)
        if key not in self.strategy_states:
            _log.warning(f"No state for {strategy_id} | {market} - skipping adaptation")
            return {"status": "no_state"}
        
        state = self.strategy_states[key]
        
        # Check if strategy is retired
        if state.status == "retired":
            return {"status": "retired", "reason": state.retirement_reason}
        
        # Check minimum trades
        perf = self.tracker.get_strategy_performance(strategy_id, market, lookback_days=30)
        if not perf or perf.total_trades < self.MIN_TRADES_FOR_ADAPTATION:
            return {
                "status": "insufficient_trades",
                "trades": perf.total_trades if perf else 0
            }
        
        results = {}
        actions_taken = []
        
        # 1. Run optimization cycle (drift detection, retraining, threshold adjustment)
        opt_result = run_optimization_cycle(state.optimizer_state, self.drift_detector)
        results["optimization"] = opt_result
        
        if opt_result["should_retrain"]:
            action = AdaptiveAction(
                timestamp=time.time(),
                strategy_id=strategy_id,
                market=market,
                action_type="retrain",
                details={"drift_detected": opt_result["drift_detected"]},
                reason=opt_result["drift_message"]
            )
            self.actions.append(action)
            actions_taken.append("retrain")
            _log.warning(f"Retraining triggered: {strategy_id} | {market}")
        
        if opt_result["confidence_threshold"] != state.optimizer_state.confidence_threshold:
            action = AdaptiveAction(
                timestamp=time.time(),
                strategy_id=strategy_id,
                market=market,
                action_type="adjust_threshold",
                details={
                    "old_threshold": state.optimizer_state.confidence_threshold,
                    "new_threshold": opt_result["confidence_threshold"]
                },
                reason="Adaptive threshold adjustment"
            )
            self.actions.append(action)
            actions_taken.append("adjust_threshold")
        
        # 2. Parameter optimization (if due)
        now = time.time()
        hours_since_opt = (now - state.last_optimization) / 3600
        
        if hours_since_opt >= self.OPTIMIZATION_INTERVAL_HOURS:
            # Note: Actual parameter optimization would call analytics.strategy_optimizer
            # For now, just log the intent
            action = AdaptiveAction(
                timestamp=now,
                strategy_id=strategy_id,
                market=market,
                action_type="optimize_params",
                details={"hours_since_last": hours_since_opt},
                reason="Scheduled parameter optimization"
            )
            self.actions.append(action)
            actions_taken.append("optimize_params")
            state.last_optimization = now
            _log.info(f"Parameter optimization due: {strategy_id} | {market}")
        
        # 3. Performance snapshot (if due)
        hours_since_snapshot = (now - state.last_snapshot) / 3600
        
        if hours_since_snapshot >= self.SNAPSHOT_INTERVAL_HOURS:
            self.tracker.snapshot_strategy(strategy_id, market, lookback_days=30)
            state.last_snapshot = now
            actions_taken.append("snapshot")
        
        # 4. Status evaluation (probation/retirement)
        status_action = self._evaluate_strategy_status(state, perf)
        if status_action:
            self.actions.append(status_action)
            actions_taken.append(status_action.action_type)
            results["status_change"] = status_action.action_type
        
        results["actions_taken"] = actions_taken
        results["current_status"] = state.status
        results["performance"] = {
            "sharpe": perf.sharpe_ratio,
            "win_rate": perf.win_rate,
            "total_trades": perf.total_trades,
            "trend": perf.performance_trend
        }
        
        self._save_state()
        
        return results
    
    def run_all_adaptations(self) -> Dict[str, Any]:
        """
        Run adaptation cycles for all active strategies.
        
        Returns:
            Dict with results for each strategy
        """
        results = {}
        
        for (strategy_id, market), state in self.strategy_states.items():
            if state.status != "retired":
                try:
                    result = self.run_adaptation_cycle(strategy_id, market)
                    results[f"{strategy_id}_{market}"] = result
                except Exception as exc:
                    _log.error(
                        f"Adaptation failed for {strategy_id} | {market}: {exc}",
                        exc_info=True
                    )
                    results[f"{strategy_id}_{market}"] = {"status": "error", "error": str(exc)}
        
        _log.info(f"Adaptation cycle complete: {len(results)} strategies processed")
        return results
    
    def _evaluate_strategy_status(
        self,
        state: StrategyState,
        perf: StrategyPerformance
    ) -> Optional[AdaptiveAction]:
        """
        Evaluate strategy health and update status (probation/retirement).
        
        Args:
            state: Current strategy state
            perf: Recent performance metrics
            
        Returns:
            AdaptiveAction if status changed, None otherwise
        """
        # Calculate simple health score (0-100)
        # Based on Sharpe, win rate, and trend
        sharpe_score = min(40, perf.sharpe_ratio / 1.5 * 40) if perf.sharpe_ratio > 0 else 0
        win_rate_score = perf.win_rate * 30
        trend_score = 30 if perf.performance_trend == "improving" else (
            15 if perf.performance_trend == "stable" else 0
        )
        
        health_score = sharpe_score + win_rate_score + trend_score
        
        now = time.time()
        
        # Check for retirement
        if health_score < self.RETIREMENT_THRESHOLD_SCORE:
            if state.status == "probation":
                # Check if probation period exceeded
                days_in_probation = (now - state.probation_start) / 86400
                if days_in_probation >= self.PROBATION_DURATION_DAYS:
                    state.status = "retired"
                    state.retirement_reason = f"Health score {health_score:.1f} below threshold after {days_in_probation:.1f} days probation"
                    
                    return AdaptiveAction(
                        timestamp=now,
                        strategy_id=state.strategy_id,
                        market=state.market,
                        action_type="retire",
                        details={"health_score": health_score, "days_in_probation": days_in_probation},
                        reason=state.retirement_reason
                    )
            else:
                # Move to probation
                state.status = "probation"
                state.probation_start = now
                
                return AdaptiveAction(
                    timestamp=now,
                    strategy_id=state.strategy_id,
                    market=state.market,
                    action_type="probation",
                    details={"health_score": health_score},
                    reason=f"Health score {health_score:.1f} below retirement threshold"
                )
        
        # Check for probation
        elif health_score < self.PROBATION_THRESHOLD_SCORE and state.status == "active":
            state.status = "probation"
            state.probation_start = now
            
            return AdaptiveAction(
                timestamp=now,
                strategy_id=state.strategy_id,
                market=state.market,
                action_type="probation",
                details={"health_score": health_score},
                reason=f"Health score {health_score:.1f} below probation threshold"
            )
        
        # Check for recovery from probation
        elif health_score >= self.PROBATION_THRESHOLD_SCORE and state.status == "probation":
            state.status = "active"
            state.probation_start = None
            
            return AdaptiveAction(
                timestamp=now,
                strategy_id=state.strategy_id,
                market=state.market,
                action_type="reactivate",
                details={"health_score": health_score},
                reason=f"Health score {health_score:.1f} recovered above probation threshold"
            )
        
        return None
    
    def get_strategy_status(
        self,
        strategy_id: str,
        market: str
    ) -> Dict[str, Any]:
        """
        Get current adaptive status for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            market: Market name
            
        Returns:
            Dict with status, metrics, and recent actions
        """
        key = (strategy_id, market)
        if key not in self.strategy_states:
            return {"status": "unknown"}
        
        state = self.strategy_states[key]
        perf = self.tracker.get_strategy_performance(strategy_id, market, lookback_days=30)
        
        # Get recent actions for this strategy
        recent_actions = [
            {
                "timestamp": a.timestamp,
                "action_type": a.action_type,
                "reason": a.reason,
                "details": a.details
            }
            for a in self.actions[-20:]  # Last 20 actions
            if a.strategy_id == strategy_id and a.market == market
        ]
        
        return {
            "status": state.status,
            "confidence_threshold": state.optimizer_state.confidence_threshold,
            "retrain_count": state.optimizer_state.retrain_count,
            "drift_alerts": state.optimizer_state.drift_alerts,
            "performance": {
                "sharpe": perf.sharpe_ratio if perf else 0.0,
                "win_rate": perf.win_rate if perf else 0.0,
                "total_trades": perf.total_trades if perf else 0,
                "trend": perf.performance_trend if perf else "unknown"
            },
            "recent_actions": recent_actions
        }
    
    def _save_state(self) -> None:
        """Save adaptive state to disk"""
        import json
        
        state_data = {
            "strategies": {
                f"{sid}_{mkt}": {
                    "strategy_id": s.strategy_id,
                    "market": s.market,
                    "status": s.status,
                    "last_optimization": s.last_optimization,
                    "last_snapshot": s.last_snapshot,
                    "probation_start": s.probation_start,
                    "retirement_reason": s.retirement_reason,
                    "optimizer": {
                        "confidence_threshold": s.optimizer_state.confidence_threshold,
                        "retrain_count": s.optimizer_state.retrain_count,
                        "drift_alerts": s.optimizer_state.drift_alerts,
                        "peak_sharpe": s.optimizer_state.peak_sharpe
                    }
                }
                for (sid, mkt), s in self.strategy_states.items()
            },
            "last_save": time.time()
        }
        
        with open(self.state_file, 'w') as f:
            json.dump(state_data, f, indent=2)
    
    def _load_state(self) -> None:
        """Load adaptive state from disk"""
        import json
        
        if not self.state_file.exists():
            return
        
        try:
            with open(self.state_file, 'r') as f:
                state_data = json.load(f)
            
            for key, data in state_data.get("strategies", {}).items():
                strategy_id = data["strategy_id"]
                market = data["market"]
                
                opt_state = OptimizerState()
                opt_data = data.get("optimizer", {})
                opt_state.confidence_threshold = opt_data.get("confidence_threshold", 0.60)
                opt_state.retrain_count = opt_data.get("retrain_count", 0)
                opt_state.drift_alerts = opt_data.get("drift_alerts", 0)
                opt_state.peak_sharpe = opt_data.get("peak_sharpe", 0.0)
                
                state = StrategyState(
                    strategy_id=strategy_id,
                    market=market,
                    optimizer_state=opt_state,
                    last_optimization=data.get("last_optimization", 0.0),
                    last_snapshot=data.get("last_snapshot", 0.0),
                    status=data.get("status", "active"),
                    probation_start=data.get("probation_start"),
                    retirement_reason=data.get("retirement_reason")
                )
                
                self.strategy_states[(strategy_id, market)] = state
            
            _log.info(f"Loaded adaptive state: {len(self.strategy_states)} strategies")
        
        except Exception as exc:
            _log.error(f"Failed to load adaptive state: {exc}", exc_info=True)
