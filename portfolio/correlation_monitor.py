"""
Correlation Monitor

Tracks correlation between strategy returns to identify clustering and diversification.

Features:
- Rolling correlation calculation
- Correlation clustering detection
- Diversification scoring
- Alerts for high correlation events
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd
from foundation.logger import logger


@dataclass
class CorrelationMetrics:
    """Correlation metrics for a strategy pair"""
    strategy_1: str
    strategy_2: str
    correlation: float
    rolling_correlation: float  # Recent 30-day correlation
    correlation_trend: str  # "increasing", "decreasing", "stable"
    is_clustered: bool  # True if correlation > threshold


@dataclass
class DiversificationScore:
    """Portfolio diversification score"""
    overall_score: float  # 0-100, higher is better
    avg_correlation: float
    max_correlation: float
    num_clusters: int
    cluster_details: List[List[str]]  # List of strategy clusters
    recommendation: str


class CorrelationMonitor:
    """
    Monitors correlation between strategy returns.
    
    Correlation thresholds:
    - < 0.3: Low correlation (good diversification)
    - 0.3-0.7: Moderate correlation
    - > 0.7: High correlation (clustering risk)
    """
    
    # Correlation thresholds
    CLUSTERING_THRESHOLD = 0.7  # Strategies above this are considered clustered
    MODERATE_CORRELATION = 0.3
    ROLLING_WINDOW = 30  # Days for rolling correlation
    
    def __init__(self):
        """Initialize correlation monitor"""
        self.returns_history: Dict[str, List[float]] = {}
        logger.info("CorrelationMonitor initialized")
    
    def update_returns(self, strategy_id: str, daily_return: float):
        """
        Update returns history for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            daily_return: Daily return (e.g., 0.01 for 1%)
        """
        if strategy_id not in self.returns_history:
            self.returns_history[strategy_id] = []
        
        self.returns_history[strategy_id].append(daily_return)
        
        # Keep only recent history (1 year = 252 trading days)
        if len(self.returns_history[strategy_id]) > 252:
            self.returns_history[strategy_id] = self.returns_history[strategy_id][-252:]
    
    def calculate_correlation_matrix(
        self,
        min_observations: int = 30
    ) -> pd.DataFrame:
        """
        Calculate correlation matrix for all strategies.
        
        Args:
            min_observations: Minimum number of observations required
            
        Returns:
            Correlation matrix as DataFrame
        """
        # Filter strategies with sufficient data
        valid_strategies = {
            sid: returns for sid, returns in self.returns_history.items()
            if len(returns) >= min_observations
        }
        
        if len(valid_strategies) < 2:
            logger.warning("Insufficient strategies for correlation calculation")
            return pd.DataFrame()
        
        # Create DataFrame from returns
        df = pd.DataFrame(valid_strategies)
        
        # Calculate correlation matrix
        corr_matrix = df.corr()
        
        logger.info(
            f"Correlation matrix calculated for {len(valid_strategies)} strategies",
            extra={
                "num_strategies": len(valid_strategies),
                "avg_correlation": corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)].mean()
            }
        )
        
        return corr_matrix
    
    def get_pairwise_correlations(
        self,
        min_observations: int = 30
    ) -> List[CorrelationMetrics]:
        """
        Get pairwise correlations between all strategies.
        
        Args:
            min_observations: Minimum number of observations required
            
        Returns:
            List of CorrelationMetrics for each strategy pair
        """
        correlations = []
        
        # Get strategies with sufficient data
        valid_strategies = {
            sid: returns for sid, returns in self.returns_history.items()
            if len(returns) >= min_observations
        }
        
        strategy_ids = list(valid_strategies.keys())
        
        # Calculate pairwise correlations
        for i, sid1 in enumerate(strategy_ids):
            for sid2 in strategy_ids[i+1:]:
                returns1 = np.array(valid_strategies[sid1])
                returns2 = np.array(valid_strategies[sid2])
                
                # Full correlation
                full_corr = np.corrcoef(returns1, returns2)[0, 1]
                
                # Rolling correlation (last 30 days)
                if len(returns1) >= self.ROLLING_WINDOW:
                    recent_returns1 = returns1[-self.ROLLING_WINDOW:]
                    recent_returns2 = returns2[-self.ROLLING_WINDOW:]
                    rolling_corr = np.corrcoef(recent_returns1, recent_returns2)[0, 1]
                else:
                    rolling_corr = full_corr
                
                # Determine trend
                if abs(rolling_corr - full_corr) < 0.1:
                    trend = "stable"
                elif rolling_corr > full_corr:
                    trend = "increasing"
                else:
                    trend = "decreasing"
                
                # Check clustering
                is_clustered = abs(rolling_corr) > self.CLUSTERING_THRESHOLD
                
                metrics = CorrelationMetrics(
                    strategy_1=sid1,
                    strategy_2=sid2,
                    correlation=full_corr,
                    rolling_correlation=rolling_corr,
                    correlation_trend=trend,
                    is_clustered=is_clustered
                )
                
                correlations.append(metrics)
        
        return correlations
    
    def detect_clusters(
        self,
        correlation_threshold: float = None
    ) -> List[List[str]]:
        """
        Detect clusters of highly correlated strategies.
        
        Args:
            correlation_threshold: Threshold for clustering (default: CLUSTERING_THRESHOLD)
            
        Returns:
            List of strategy clusters
        """
        if correlation_threshold is None:
            correlation_threshold = self.CLUSTERING_THRESHOLD
        
        # Get correlation matrix
        corr_matrix = self.calculate_correlation_matrix()
        
        if corr_matrix.empty:
            return []
        
        # Find clusters using simple threshold-based approach
        strategy_ids = corr_matrix.index.tolist()
        clusters = []
        assigned = set()
        
        for i, sid1 in enumerate(strategy_ids):
            if sid1 in assigned:
                continue
            
            # Start new cluster
            cluster = [sid1]
            assigned.add(sid1)
            
            # Find correlated strategies
            for sid2 in strategy_ids[i+1:]:
                if sid2 in assigned:
                    continue
                
                # Check if sid2 is correlated with all strategies in cluster
                is_correlated = all(
                    abs(corr_matrix.loc[sid2, cluster_sid]) > correlation_threshold
                    for cluster_sid in cluster
                )
                
                if is_correlated:
                    cluster.append(sid2)
                    assigned.add(sid2)
            
            # Only keep clusters with 2+ strategies
            if len(cluster) > 1:
                clusters.append(cluster)
        
        logger.info(
            f"Detected {len(clusters)} correlation clusters",
            extra={
                "num_clusters": len(clusters),
                "cluster_sizes": [len(c) for c in clusters]
            }
        )
        
        return clusters
    
    def calculate_diversification_score(self) -> DiversificationScore:
        """
        Calculate overall portfolio diversification score.
        
        Returns:
            DiversificationScore with metrics and recommendation
        """
        # Get correlation matrix
        corr_matrix = self.calculate_correlation_matrix()
        
        if corr_matrix.empty or len(corr_matrix) < 2:
            return DiversificationScore(
                overall_score=50.0,
                avg_correlation=0.0,
                max_correlation=0.0,
                num_clusters=0,
                cluster_details=[],
                recommendation="Insufficient data for diversification analysis"
            )
        
        # Calculate metrics
        # Get upper triangle (excluding diagonal)
        upper_triangle = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
        avg_corr = np.mean(np.abs(upper_triangle))
        max_corr = np.max(np.abs(upper_triangle))
        
        # Detect clusters
        clusters = self.detect_clusters()
        num_clusters = len(clusters)
        
        # Calculate diversification score (0-100)
        # Lower correlation = higher score
        corr_score = max(0, 100 * (1 - avg_corr))
        
        # Penalty for clusters
        cluster_penalty = num_clusters * 10
        
        overall_score = max(0, min(100, corr_score - cluster_penalty))
        
        # Generate recommendation
        if overall_score >= 80:
            recommendation = "Excellent diversification"
        elif overall_score >= 60:
            recommendation = "Good diversification"
        elif overall_score >= 40:
            recommendation = "Moderate diversification - consider reducing correlated positions"
        else:
            recommendation = "Poor diversification - high clustering risk detected"
        
        score = DiversificationScore(
            overall_score=overall_score,
            avg_correlation=avg_corr,
            max_correlation=max_corr,
            num_clusters=num_clusters,
            cluster_details=clusters,
            recommendation=recommendation
        )
        
        logger.info(
            "Diversification score calculated",
            extra={
                "overall_score": overall_score,
                "avg_correlation": avg_corr,
                "num_clusters": num_clusters
            }
        )
        
        return score
    
    def get_high_correlation_alerts(
        self,
        threshold: float = None
    ) -> List[Tuple[str, str, float]]:
        """
        Get alerts for strategy pairs with high correlation.
        
        Args:
            threshold: Correlation threshold for alerts (default: CLUSTERING_THRESHOLD)
            
        Returns:
            List of (strategy_1, strategy_2, correlation) tuples
        """
        if threshold is None:
            threshold = self.CLUSTERING_THRESHOLD
        
        correlations = self.get_pairwise_correlations()
        
        alerts = [
            (c.strategy_1, c.strategy_2, c.rolling_correlation)
            for c in correlations
            if abs(c.rolling_correlation) > threshold
        ]
        
        if alerts:
            logger.warning(
                f"High correlation detected for {len(alerts)} strategy pairs",
                extra={"num_alerts": len(alerts), "threshold": threshold}
            )
        
        return alerts
