"""
Live Readiness Score — Computes overall readiness score for live deployment.

Combines metrics from all validators to produce a single 0-100% score
that indicates whether the system is ready for live trading.
"""

from __future__ import annotations

from dataclasses import dataclass

from foundation.logger import get_logger
from production_readiness.metrics_aggregator import AggregatedMetrics, collect_all_metrics
from production_readiness.operational_validator import OperationalValidation, validate

_log = get_logger("production_readiness", "live_readiness_score")


@dataclass
class ReadinessScore:
    """Overall readiness score and breakdown."""
    overall_score: float  # 0.0 to 1.0
    overall_percentage: float  # 0 to 100
    is_ready_for_live: bool
    operational_score: float
    blockers: list[str]
    warnings: list[str]
    recommendation: str


class LiveReadinessScorer:
    """Computes live readiness score."""
    
    # Minimum score required for live deployment
    MIN_SCORE_FOR_LIVE = 0.85  # 85%
    
    def __init__(self):
        pass
    
    def compute_score(
        self,
        metrics: AggregatedMetrics | None = None,
        validation: OperationalValidation | None = None,
    ) -> ReadinessScore:
        """
        Compute overall readiness score.
        
        Args:
            metrics: Pre-collected metrics (optional)
            validation: Pre-computed validation (optional)
        
        Returns:
            ReadinessScore with overall score and breakdown
        """
        # Collect metrics if not provided
        if metrics is None:
            metrics = collect_all_metrics()
        
        # Validate if not provided
        if validation is None:
            validation = validate(metrics)
        
        # Operational score is the primary component
        operational_score = validation.overall_score
        
        # Overall score (can be extended with more components later)
        overall_score = operational_score
        overall_percentage = overall_score * 100.0
        
        # Determine if ready for live
        is_ready_for_live = (
            overall_score >= self.MIN_SCORE_FOR_LIVE
            and validation.overall_status != "FAIL"
            and len(validation.blockers) == 0
        )
        
        # Generate recommendation
        recommendation = self._generate_recommendation(
            overall_score, validation, is_ready_for_live
        )
        
        return ReadinessScore(
            overall_score=overall_score,
            overall_percentage=overall_percentage,
            is_ready_for_live=is_ready_for_live,
            operational_score=operational_score,
            blockers=validation.blockers,
            warnings=validation.warnings,
            recommendation=recommendation,
        )
    
    def _generate_recommendation(
        self,
        score: float,
        validation: OperationalValidation,
        is_ready: bool,
    ) -> str:
        """Generate human-readable recommendation."""
        if is_ready:
            return (
                f"✅ READY FOR LIVE DEPLOYMENT\n\n"
                f"Score: {score * 100:.1f}%\n"
                f"All critical requirements met. System is ready for live trading."
            )
        
        if validation.blockers:
            blockers_text = "\n".join(f"  - {b}" for b in validation.blockers)
            return (
                f"❌ NOT READY FOR LIVE DEPLOYMENT\n\n"
                f"Score: {score * 100:.1f}%\n"
                f"Blockers:\n{blockers_text}\n\n"
                f"Resolve all blockers before live deployment."
            )
        
        if score < self.MIN_SCORE_FOR_LIVE:
            return (
                f"⚠️ NOT READY FOR LIVE DEPLOYMENT\n\n"
                f"Score: {score * 100:.1f}% (minimum: {self.MIN_SCORE_FOR_LIVE * 100:.1f}%)\n"
                f"Continue paper trading to improve metrics."
            )
        
        return (
            f"⚠️ CAUTION\n\n"
            f"Score: {score * 100:.1f}%\n"
            f"Some warnings present. Review carefully before live deployment."
        )


# Global singleton instance
_scorer = LiveReadinessScorer()


def compute_score(
    metrics: AggregatedMetrics | None = None,
    validation: OperationalValidation | None = None,
) -> ReadinessScore:
    """Convenience function to compute score using the global scorer."""
    return _scorer.compute_score(metrics, validation)
