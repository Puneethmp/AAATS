"""
Risk Aggregator

Aggregates risk metrics across all portfolio intelligence modules.

Features:
- Unified risk dashboard
- Cross-module risk scoring
- Portfolio-level risk assessment
- Risk alert generation
"""

from dataclasses import dataclass
from typing import Dict, List
from foundation.logger import logger


@dataclass
class PortfolioRiskMetrics:
    """Aggregated portfolio risk metrics"""
    overall_risk_score: float  # 0-100, lower is better
    risk_level: str  # "low", "moderate", "high", "critical"
    
    # Component scores
    health_risk_score: float
    volatility_risk_score: float
    drawdown_risk_score: float
    correlation_risk_score: float
    exposure_risk_score: float
    throttle_risk_score: float
    regime_risk_score: float
    
    # Alerts
    active_alerts: List[str]
    warnings: List[str]
    
    # Recommendations
    primary_recommendation: str
    action_items: List[str]


class RiskAggregator:
    """
    Aggregates risk metrics from all portfolio intelligence modules.
    
    Risk scoring:
    - 0-25: Low risk (green)
    - 25-50: Moderate risk (yellow)
    - 50-75: High risk (orange)
    - 75-100: Critical risk (red)
    """
    
    # Risk score weights
    WEIGHT_HEALTH = 0.20
    WEIGHT_VOLATILITY = 0.15
    WEIGHT_DRAWDOWN = 0.25
    WEIGHT_CORRELATION = 0.10
    WEIGHT_EXPOSURE = 0.15
    WEIGHT_THROTTLE = 0.10
    WEIGHT_REGIME = 0.05
    
    # Risk thresholds
    MODERATE_RISK_THRESHOLD = 25
    HIGH_RISK_THRESHOLD = 50
    CRITICAL_RISK_THRESHOLD = 75
    
    def __init__(self):
        """Initialize risk aggregator"""
        logger.info("RiskAggregator initialized")
    
    def aggregate_risk(
        self,
        avg_health_score: float = 75.0,
        volatility_ratio: float = 1.0,
        portfolio_drawdown: float = 0.0,
        avg_correlation: float = 0.3,
        gross_exposure_pct: float = 0.40,
        is_throttled: bool = False,
        throttle_level: str = "none",
        regime_transition_risk: str = "low"
    ) -> PortfolioRiskMetrics:
        """
        Aggregate risk metrics from all modules.
        
        Args:
            avg_health_score: Average strategy health score (0-100)
            volatility_ratio: Current vol / Target vol
            portfolio_drawdown: Current portfolio drawdown (negative)
            avg_correlation: Average correlation between strategies
            gross_exposure_pct: Gross exposure as % of capital
            is_throttled: Whether capital is throttled
            throttle_level: Throttle level if active
            regime_transition_risk: Regime transition risk level
            
        Returns:
            PortfolioRiskMetrics with aggregated risk assessment
        """
        # Calculate component risk scores
        health_risk = self._score_health_risk(avg_health_score)
        vol_risk = self._score_volatility_risk(volatility_ratio)
        dd_risk = self._score_drawdown_risk(portfolio_drawdown)
        corr_risk = self._score_correlation_risk(avg_correlation)
        exposure_risk = self._score_exposure_risk(gross_exposure_pct)
        throttle_risk = self._score_throttle_risk(is_throttled, throttle_level)
        regime_risk = self._score_regime_risk(regime_transition_risk)
        
        # Calculate weighted overall risk score
        overall_risk = (
            health_risk * self.WEIGHT_HEALTH +
            vol_risk * self.WEIGHT_VOLATILITY +
            dd_risk * self.WEIGHT_DRAWDOWN +
            corr_risk * self.WEIGHT_CORRELATION +
            exposure_risk * self.WEIGHT_EXPOSURE +
            throttle_risk * self.WEIGHT_THROTTLE +
            regime_risk * self.WEIGHT_REGIME
        )
        
        # Determine risk level
        if overall_risk < self.MODERATE_RISK_THRESHOLD:
            risk_level = "low"
        elif overall_risk < self.HIGH_RISK_THRESHOLD:
            risk_level = "moderate"
        elif overall_risk < self.CRITICAL_RISK_THRESHOLD:
            risk_level = "high"
        else:
            risk_level = "critical"
        
        # Generate alerts and warnings
        alerts, warnings = self._generate_alerts(
            health_risk, vol_risk, dd_risk, corr_risk,
            exposure_risk, throttle_risk, regime_risk,
            portfolio_drawdown, is_throttled
        )
        
        # Generate recommendations
        recommendation, action_items = self._generate_recommendations(
            risk_level, alerts, warnings,
            health_risk, vol_risk, dd_risk, exposure_risk
        )
        
        metrics = PortfolioRiskMetrics(
            overall_risk_score=overall_risk,
            risk_level=risk_level,
            health_risk_score=health_risk,
            volatility_risk_score=vol_risk,
            drawdown_risk_score=dd_risk,
            correlation_risk_score=corr_risk,
            exposure_risk_score=exposure_risk,
            throttle_risk_score=throttle_risk,
            regime_risk_score=regime_risk,
            active_alerts=alerts,
            warnings=warnings,
            primary_recommendation=recommendation,
            action_items=action_items
        )
        
        logger.info(
            f"Risk aggregated: {risk_level}",
            extra={
                "overall_risk": overall_risk,
                "risk_level": risk_level,
                "num_alerts": len(alerts),
                "num_warnings": len(warnings)
            }
        )
        
        if risk_level in ["high", "critical"]:
            logger.warning(
                f"{risk_level.upper()} RISK DETECTED",
                extra={
                    "overall_risk": overall_risk,
                    "alerts": alerts,
                    "recommendation": recommendation
                }
            )
        
        return metrics
    
    def _score_health_risk(self, avg_health_score: float) -> float:
        """Score health risk (0-100, lower health = higher risk)"""
        # Invert health score: 100 health = 0 risk, 0 health = 100 risk
        return 100 - avg_health_score
    
    def _score_volatility_risk(self, volatility_ratio: float) -> float:
        """Score volatility risk (0-100)"""
        # Vol ratio 1.0 = 0 risk, 2.0+ = 100 risk
        if volatility_ratio <= 1.0:
            return 0.0
        elif volatility_ratio >= 2.0:
            return 100.0
        else:
            return (volatility_ratio - 1.0) * 100
    
    def _score_drawdown_risk(self, drawdown: float) -> float:
        """Score drawdown risk (0-100)"""
        # 0% DD = 0 risk, -20% DD = 100 risk
        if drawdown >= 0:
            return 0.0
        elif drawdown <= -0.20:
            return 100.0
        else:
            return abs(drawdown) / 0.20 * 100
    
    def _score_correlation_risk(self, avg_correlation: float) -> float:
        """Score correlation risk (0-100)"""
        # Correlation 0.3 = 0 risk, 0.9+ = 100 risk
        if avg_correlation <= 0.3:
            return 0.0
        elif avg_correlation >= 0.9:
            return 100.0
        else:
            return (avg_correlation - 0.3) / 0.6 * 100
    
    def _score_exposure_risk(self, gross_exposure_pct: float) -> float:
        """Score exposure risk (0-100)"""
        # 40% exposure = 0 risk, 80%+ = 100 risk
        if gross_exposure_pct <= 0.40:
            return 0.0
        elif gross_exposure_pct >= 0.80:
            return 100.0
        else:
            return (gross_exposure_pct - 0.40) / 0.40 * 100
    
    def _score_throttle_risk(self, is_throttled: bool, throttle_level: str) -> float:
        """Score throttle risk (0-100)"""
        if not is_throttled:
            return 0.0
        
        throttle_scores = {
            "light": 25.0,
            "moderate": 50.0,
            "heavy": 75.0,
            "full": 100.0
        }
        return throttle_scores.get(throttle_level, 0.0)
    
    def _score_regime_risk(self, transition_risk: str) -> float:
        """Score regime transition risk (0-100)"""
        risk_scores = {
            "low": 0.0,
            "moderate": 50.0,
            "high": 100.0
        }
        return risk_scores.get(transition_risk, 0.0)
    
    def _generate_alerts(
        self,
        health_risk: float,
        vol_risk: float,
        dd_risk: float,
        corr_risk: float,
        exposure_risk: float,
        throttle_risk: float,
        regime_risk: float,
        portfolio_drawdown: float,
        is_throttled: bool
    ) -> tuple[List[str], List[str]]:
        """Generate alerts and warnings"""
        alerts = []
        warnings = []
        
        # Critical alerts (risk > 75)
        if dd_risk > 75:
            alerts.append(f"CRITICAL: Portfolio drawdown {portfolio_drawdown:.1%}")
        if vol_risk > 75:
            alerts.append("CRITICAL: Extreme volatility detected")
        if exposure_risk > 75:
            alerts.append("CRITICAL: Excessive portfolio exposure")
        
        # High risk warnings (risk > 50)
        if health_risk > 50:
            warnings.append("Strategy health deteriorating")
        if corr_risk > 50:
            warnings.append("High correlation between strategies")
        if throttle_risk > 50:
            warnings.append(f"Capital throttle active: {is_throttled}")
        if regime_risk > 50:
            warnings.append("High regime transition risk")
        
        return alerts, warnings
    
    def _generate_recommendations(
        self,
        risk_level: str,
        alerts: List[str],
        warnings: List[str],
        health_risk: float,
        vol_risk: float,
        dd_risk: float,
        exposure_risk: float
    ) -> tuple[str, List[str]]:
        """Generate recommendations and action items"""
        action_items = []
        
        if risk_level == "critical":
            recommendation = "DEFENSIVE MODE: Reduce exposure immediately, preserve capital"
            action_items = [
                "Close underperforming positions",
                "Reduce gross exposure to <30%",
                "Halt new position entries",
                "Review all open positions",
                "Consider manual intervention"
            ]
        elif risk_level == "high":
            recommendation = "CAUTION: Reduce risk exposure and monitor closely"
            action_items = [
                "Reduce position sizes by 30-50%",
                "Close weakest strategies",
                "Tighten stop losses",
                "Increase monitoring frequency"
            ]
        elif risk_level == "moderate":
            recommendation = "MONITOR: Maintain current exposure with increased vigilance"
            action_items = [
                "Monitor drawdown levels",
                "Review strategy health scores",
                "Check correlation metrics",
                "Prepare contingency plans"
            ]
        else:  # low
            recommendation = "NORMAL: Continue operations with standard risk management"
            action_items = [
                "Maintain current allocations",
                "Continue regular monitoring",
                "Look for new opportunities"
            ]
        
        # Add specific action items based on highest risks
        if dd_risk > 60:
            action_items.insert(0, "Priority: Address drawdown - reduce exposure")
        if vol_risk > 60:
            action_items.insert(0, "Priority: Reduce volatility exposure")
        if exposure_risk > 60:
            action_items.insert(0, "Priority: Reduce gross exposure")
        if health_risk > 60:
            action_items.insert(0, "Priority: Pause weak strategies")
        
        return recommendation, action_items
    
    def get_risk_summary(self, metrics: PortfolioRiskMetrics) -> str:
        """
        Get human-readable risk summary.
        
        Args:
            metrics: PortfolioRiskMetrics
            
        Returns:
            Summary string
        """
        summary = f"Portfolio Risk: {metrics.risk_level.upper()} ({metrics.overall_risk_score:.1f}/100)\n\n"
        
        if metrics.active_alerts:
            summary += "ALERTS:\n"
            for alert in metrics.active_alerts:
                summary += f"  - {alert}\n"
            summary += "\n"
        
        if metrics.warnings:
            summary += "WARNINGS:\n"
            for warning in metrics.warnings:
                summary += f"  - {warning}\n"
            summary += "\n"
        
        summary += f"RECOMMENDATION: {metrics.primary_recommendation}\n\n"
        
        if metrics.action_items:
            summary += "ACTION ITEMS:\n"
            for i, item in enumerate(metrics.action_items, 1):
                summary += f"  {i}. {item}\n"
        
        return summary
