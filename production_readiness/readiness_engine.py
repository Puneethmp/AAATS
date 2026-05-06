"""
Readiness Engine — Main orchestrator for production readiness checks.

This is the high-level API that coordinates all production readiness
components and provides a simple interface for checking system readiness.
"""

from __future__ import annotations

from dataclasses import dataclass

from foundation.logger import get_logger
from production_readiness.deployment_gatekeeper import (
    DeploymentDecision,
    check_deployment_allowed,
)
from production_readiness.live_readiness_score import ReadinessScore, compute_score
from production_readiness.metrics_aggregator import AggregatedMetrics, collect_all_metrics
from production_readiness.operational_validator import (
    OperationalValidation,
    validate,
)

_log = get_logger("production_readiness", "readiness_engine")


@dataclass
class ProductionReadinessReport:
    """Complete production readiness report."""
    metrics: AggregatedMetrics
    validation: OperationalValidation
    score: ReadinessScore
    deployment_decision: DeploymentDecision
    
    @property
    def is_ready(self) -> bool:
        """Check if system is ready for live deployment."""
        return self.deployment_decision.allowed
    
    @property
    def overall_score_percentage(self) -> float:
        """Get overall score as percentage."""
        return self.score.overall_percentage
    
    @property
    def has_blockers(self) -> bool:
        """Check if there are any blockers."""
        return len(self.deployment_decision.blockers) > 0


class ReadinessEngine:
    """Main orchestrator for production readiness checks."""
    
    def __init__(self):
        pass
    
    def generate_report(self) -> ProductionReadinessReport:
        """
        Generate complete production readiness report.
        
        This is the main entry point for checking system readiness.
        It orchestrates all components and returns a comprehensive report.
        
        Returns:
            ProductionReadinessReport with all readiness information
        """
        try:
            _log.info("Generating production readiness report...")
            
            # Step 1: Collect metrics
            _log.debug("Collecting metrics...")
            metrics = collect_all_metrics()
            
            # Step 2: Validate operational requirements
            _log.debug("Validating operational requirements...")
            validation = validate(metrics)
            
            # Step 3: Compute readiness score
            _log.debug("Computing readiness score...")
            score = compute_score(metrics, validation)
            
            # Step 4: Check deployment gate
            _log.debug("Checking deployment gate...")
            deployment_decision = check_deployment_allowed()
            
            # Create report
            report = ProductionReadinessReport(
                metrics=metrics,
                validation=validation,
                score=score,
                deployment_decision=deployment_decision,
            )
            
            # Log summary
            _log.info(
                f"Production readiness report complete: "
                f"Score={report.overall_score_percentage:.1f}%, "
                f"Ready={report.is_ready}, "
                f"Blockers={len(report.deployment_decision.blockers)}"
            )
            
            return report
        
        except Exception as e:
            _log.error(f"Failed to generate readiness report: {e}")
            # Return a safe default report
            return ProductionReadinessReport(
                metrics=AggregatedMetrics(),
                validation=OperationalValidation(
                    results=[],
                    overall_status="FAIL",
                    overall_score=0.0,
                    blockers=["Failed to generate report"],
                    warnings=[],
                ),
                score=ReadinessScore(
                    overall_score=0.0,
                    overall_percentage=0.0,
                    is_ready_for_live=False,
                    operational_score=0.0,
                    blockers=["Failed to generate report"],
                    warnings=[],
                    recommendation="System error - cannot assess readiness",
                ),
                deployment_decision=DeploymentDecision(
                    allowed=False,
                    reason="System error during readiness check",
                    readiness_score=0.0,
                    timestamp="",
                    blockers=["System error"],
                ),
            )
    
    def quick_check(self) -> bool:
        """
        Quick check if system is ready for live deployment.
        
        Returns:
            True if ready, False otherwise
        """
        try:
            report = self.generate_report()
            return report.is_ready
        except Exception as e:
            _log.error(f"Quick check failed: {e}")
            return False


# Global singleton instance
_engine = ReadinessEngine()


def generate_report() -> ProductionReadinessReport:
    """Convenience function to generate report using the global engine."""
    return _engine.generate_report()


def quick_check() -> bool:
    """Convenience function to quick check using the global engine."""
    return _engine.quick_check()
