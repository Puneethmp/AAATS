"""
Strategy Health Scorer

Evaluates strategy performance and health metrics to inform capital allocation decisions.

Health Score Components:
- Recent performance (Sharpe, win rate, profit factor)
- Consistency (volatility of returns)
- Drawdown recovery
- Signal quality (confidence scores)
- Regime alignment
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
from foundation.logger import logger


@dataclass
class StrategyMetrics:
    """Performance metrics for a strategy"""
    strategy_id: str
    market: str
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    avg_return: float
    return_volatility: float
    max_drawdown: float
    current_drawdown: float
    days_in_drawdown: int
    total_trades: int
    recent_trades: int  # Last 30 days
    avg_confidence: float
    regime_alignment: float  # 0-1, how well strategy matches current regime


@dataclass
class HealthScore:
    """Health score for a strategy"""
    strategy_id: str
    market: str
    overall_score: float  # 0-100
    performance_score: float
    consistency_score: float
    drawdown_score: float
    signal_quality_score: float
    regime_score: float
    recommendation: str  # "increase", "maintain", "reduce", "pause"
    reason: str


class StrategyHealthScorer:
    """
    Evaluates strategy health and provides capital allocation recommendations.
    
    Scoring methodology:
    - Performance (30%): Sharpe, win rate, profit factor
    - Consistency (25%): Return volatility, trade frequency
    - Drawdown (25%): Current drawdown, recovery time
    - Signal Quality (10%): Average confidence scores
    - Regime Alignment (10%): Strategy-regime fit
    """
    
    # Score weights
    WEIGHT_PERFORMANCE = 0.30
    WEIGHT_CONSISTENCY = 0.25
    WEIGHT_DRAWDOWN = 0.25
    WEIGHT_SIGNAL_QUALITY = 0.10
    WEIGHT_REGIME = 0.10
    
    # Thresholds
    MIN_TRADES_FOR_SCORING = 10
    SHARPE_TARGET = 1.5
    WIN_RATE_TARGET = 0.55
    PROFIT_FACTOR_TARGET = 1.5
    MAX_ACCEPTABLE_DRAWDOWN = -0.15
    
    def __init__(self):
        """Initialize strategy health scorer"""
        logger.info("StrategyHealthScorer initialized")
    
    def score_strategy(self, metrics: StrategyMetrics) -> HealthScore:
        """
        Calculate comprehensive health score for a strategy.
        
        Args:
            metrics: Strategy performance metrics
            
        Returns:
            HealthScore with overall score and component scores
        """
        # Check minimum trades
        if metrics.total_trades < self.MIN_TRADES_FOR_SCORING:
            return HealthScore(
                strategy_id=metrics.strategy_id,
                market=metrics.market,
                overall_score=50.0,  # Neutral score
                performance_score=50.0,
                consistency_score=50.0,
                drawdown_score=50.0,
                signal_quality_score=50.0,
                regime_score=50.0,
                recommendation="maintain",
                reason=f"Insufficient trades ({metrics.total_trades} < {self.MIN_TRADES_FOR_SCORING})"
            )
        
        # Calculate component scores
        perf_score = self._score_performance(metrics)
        consistency_score = self._score_consistency(metrics)
        drawdown_score = self._score_drawdown(metrics)
        signal_score = self._score_signal_quality(metrics)
        regime_score = self._score_regime_alignment(metrics)
        
        # Calculate weighted overall score
        overall = (
            perf_score * self.WEIGHT_PERFORMANCE +
            consistency_score * self.WEIGHT_CONSISTENCY +
            drawdown_score * self.WEIGHT_DRAWDOWN +
            signal_score * self.WEIGHT_SIGNAL_QUALITY +
            regime_score * self.WEIGHT_REGIME
        )
        
        # Generate recommendation
        recommendation, reason = self._generate_recommendation(
            overall, metrics, perf_score, drawdown_score
        )
        
        health_score = HealthScore(
            strategy_id=metrics.strategy_id,
            market=metrics.market,
            overall_score=overall,
            performance_score=perf_score,
            consistency_score=consistency_score,
            drawdown_score=drawdown_score,
            signal_quality_score=signal_score,
            regime_score=regime_score,
            recommendation=recommendation,
            reason=reason
        )
        
        logger.info(
            f"Strategy health scored: {metrics.strategy_id} ({metrics.market})",
            extra={
                "strategy_id": metrics.strategy_id,
                "market": metrics.market,
                "overall_score": overall,
                "recommendation": recommendation
            }
        )
        
        return health_score
    
    def score_multiple_strategies(
        self, 
        metrics_list: List[StrategyMetrics]
    ) -> Dict[str, HealthScore]:
        """
        Score multiple strategies and return ranked results.
        
        Args:
            metrics_list: List of strategy metrics
            
        Returns:
            Dictionary mapping strategy_id to HealthScore
        """
        scores = {}
        for metrics in metrics_list:
            score = self.score_strategy(metrics)
            scores[metrics.strategy_id] = score
        
        # Log summary
        sorted_scores = sorted(
            scores.values(), 
            key=lambda x: x.overall_score, 
            reverse=True
        )
        
        logger.info(
            f"Scored {len(scores)} strategies",
            extra={
                "total_strategies": len(scores),
                "top_strategy": sorted_scores[0].strategy_id if sorted_scores else None,
                "top_score": sorted_scores[0].overall_score if sorted_scores else None
            }
        )
        
        return scores
    
    def _score_performance(self, metrics: StrategyMetrics) -> float:
        """Score based on Sharpe, win rate, and profit factor (0-100)"""
        # Sharpe component (0-40 points)
        sharpe_score = min(40, (metrics.sharpe_ratio / self.SHARPE_TARGET) * 40)
        sharpe_score = max(0, sharpe_score)
        
        # Win rate component (0-30 points)
        win_rate_score = min(30, (metrics.win_rate / self.WIN_RATE_TARGET) * 30)
        win_rate_score = max(0, win_rate_score)
        
        # Profit factor component (0-30 points)
        pf_score = min(30, (metrics.profit_factor / self.PROFIT_FACTOR_TARGET) * 30)
        pf_score = max(0, pf_score)
        
        return sharpe_score + win_rate_score + pf_score
    
    def _score_consistency(self, metrics: StrategyMetrics) -> float:
        """Score based on return volatility and trade frequency (0-100)"""
        # Lower volatility is better (0-60 points)
        # Normalize: 0.02 daily vol = 100, 0.05 = 40, >0.10 = 0
        if metrics.return_volatility <= 0:
            vol_score = 60.0
        else:
            vol_score = max(0, 60 * (1 - metrics.return_volatility / 0.10))
        
        # Trade frequency (0-40 points)
        # Recent trades should be consistent with total
        if metrics.total_trades > 0:
            expected_recent = 30 * (metrics.total_trades / 365)  # Assume 1 year
            if expected_recent > 0:
                freq_score = min(40, (metrics.recent_trades / expected_recent) * 40)
            else:
                freq_score = 20.0  # Neutral
        else:
            freq_score = 0.0
        
        return vol_score + freq_score
    
    def _score_drawdown(self, metrics: StrategyMetrics) -> float:
        """Score based on current drawdown and recovery time (0-100)"""
        # Current drawdown severity (0-60 points)
        # 0% DD = 60, -10% = 30, -15% = 10, worse = 0
        if metrics.current_drawdown >= 0:
            dd_severity_score = 60.0
        else:
            dd_severity_score = max(
                0, 
                60 * (1 - abs(metrics.current_drawdown) / abs(self.MAX_ACCEPTABLE_DRAWDOWN))
            )
        
        # Recovery time (0-40 points)
        # 0 days = 40, 30 days = 20, 90+ days = 0
        if metrics.days_in_drawdown == 0:
            recovery_score = 40.0
        else:
            recovery_score = max(0, 40 * (1 - metrics.days_in_drawdown / 90))
        
        return dd_severity_score + recovery_score
    
    def _score_signal_quality(self, metrics: StrategyMetrics) -> float:
        """Score based on average signal confidence (0-100)"""
        # Confidence is 0-1, scale to 0-100
        return metrics.avg_confidence * 100
    
    def _score_regime_alignment(self, metrics: StrategyMetrics) -> float:
        """Score based on strategy-regime fit (0-100)"""
        # Regime alignment is 0-1, scale to 0-100
        return metrics.regime_alignment * 100
    
    def _generate_recommendation(
        self,
        overall_score: float,
        metrics: StrategyMetrics,
        perf_score: float,
        drawdown_score: float
    ) -> tuple[str, str]:
        """
        Generate capital allocation recommendation.
        
        Returns:
            (recommendation, reason) tuple
        """
        # Critical conditions
        if metrics.current_drawdown < self.MAX_ACCEPTABLE_DRAWDOWN:
            return "pause", f"Drawdown {metrics.current_drawdown:.1%} exceeds limit"
        
        if metrics.recent_trades == 0 and metrics.total_trades > 0:
            return "reduce", "No recent trading activity"
        
        # Score-based recommendations
        if overall_score >= 80:
            return "increase", f"Excellent health (score: {overall_score:.1f})"
        elif overall_score >= 65:
            return "maintain", f"Good health (score: {overall_score:.1f})"
        elif overall_score >= 50:
            return "reduce", f"Moderate health (score: {overall_score:.1f})"
        else:
            return "pause", f"Poor health (score: {overall_score:.1f})"
