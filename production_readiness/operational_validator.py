"""
Operational Validator — Validates operational requirements for live deployment.

Checks:
  - Minimum paper trading duration
  - Stable performance metrics
  - Infrastructure reliability
  - Risk management effectiveness
  - Recovery capabilities
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from foundation.logger import get_logger
from production_readiness.metrics_aggregator import AggregatedMetrics, collect_all_metrics

_log = get_logger("production_readiness", "operational_validator")

ValidationStatus = Literal["PASS", "FAIL", "WARNING"]


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    check_name: str
    status: ValidationStatus
    score: float  # 0.0 to 1.0
    message: str
    required_for_live: bool = True


@dataclass
class OperationalValidation:
    """Complete operational validation results."""
    results: list[ValidationResult]
    overall_status: ValidationStatus
    overall_score: float  # 0.0 to 1.0
    blockers: list[str]
    warnings: list[str]


class OperationalValidator:
    """Validates operational requirements for live deployment."""
    
    # Minimum requirements for live deployment
    MIN_PAPER_TRADING_DAYS = 14  # 2 weeks minimum
    MIN_WIN_RATE = 0.45  # 45% minimum
    MAX_DRAWDOWN_THRESHOLD = -0.15  # -15% maximum
    MIN_FILL_RATE = 0.90  # 90% minimum
    MIN_UPTIME = 0.95  # 95% minimum
    MIN_DASHBOARD_SYNC = 0.90  # 90% minimum
    
    def __init__(self):
        pass
    
    def validate(self, metrics: AggregatedMetrics | None = None) -> OperationalValidation:
        """
        Perform complete operational validation.
        
        Args:
            metrics: Pre-collected metrics (optional, will collect if not provided)
        
        Returns:
            OperationalValidation with all check results
        """
        if metrics is None:
            metrics = collect_all_metrics()
        
        results: list[ValidationResult] = []
        
        # 1. Paper trading duration
        results.append(self._validate_paper_trading_duration(metrics))
        
        # 2. Win rate
        results.append(self._validate_win_rate(metrics))
        
        # 3. Drawdown
        results.append(self._validate_drawdown(metrics))
        
        # 4. Fill rate
        results.append(self._validate_fill_rate(metrics))
        
        # 5. Infrastructure uptime
        results.append(self._validate_uptime(metrics))
        
        # 6. Dashboard sync health
        results.append(self._validate_dashboard_sync(metrics))
        
        # 7. Total trades
        results.append(self._validate_total_trades(metrics))
        
        # Compute overall status
        overall_status, overall_score, blockers, warnings = self._compute_overall_status(results)
        
        return OperationalValidation(
            results=results,
            overall_status=overall_status,
            overall_score=overall_score,
            blockers=blockers,
            warnings=warnings,
        )
    
    def _validate_paper_trading_duration(self, metrics: AggregatedMetrics) -> ValidationResult:
        """Validate minimum paper trading duration."""
        days = metrics.paper_trading.days_trading
        
        if days >= self.MIN_PAPER_TRADING_DAYS:
            return ValidationResult(
                check_name="Paper Trading Duration",
                status="PASS",
                score=1.0,
                message=f"{days} days (minimum: {self.MIN_PAPER_TRADING_DAYS} days)",
                required_for_live=True,
            )
        elif days >= self.MIN_PAPER_TRADING_DAYS * 0.7:
            return ValidationResult(
                check_name="Paper Trading Duration",
                status="WARNING",
                score=days / self.MIN_PAPER_TRADING_DAYS,
                message=f"{days} days (minimum: {self.MIN_PAPER_TRADING_DAYS} days) - Close to minimum",
                required_for_live=True,
            )
        else:
            return ValidationResult(
                check_name="Paper Trading Duration",
                status="FAIL",
                score=days / self.MIN_PAPER_TRADING_DAYS,
                message=f"{days} days (minimum: {self.MIN_PAPER_TRADING_DAYS} days) - Insufficient",
                required_for_live=True,
            )
    
    def _validate_win_rate(self, metrics: AggregatedMetrics) -> ValidationResult:
        """Validate win rate."""
        win_rate = metrics.paper_trading.win_rate
        
        if win_rate >= self.MIN_WIN_RATE:
            return ValidationResult(
                check_name="Win Rate",
                status="PASS",
                score=1.0,
                message=f"{win_rate:.1%} (minimum: {self.MIN_WIN_RATE:.1%})",
                required_for_live=True,
            )
        elif win_rate >= self.MIN_WIN_RATE * 0.9:
            return ValidationResult(
                check_name="Win Rate",
                status="WARNING",
                score=win_rate / self.MIN_WIN_RATE,
                message=f"{win_rate:.1%} (minimum: {self.MIN_WIN_RATE:.1%}) - Below target",
                required_for_live=True,
            )
        else:
            return ValidationResult(
                check_name="Win Rate",
                status="FAIL",
                score=win_rate / self.MIN_WIN_RATE,
                message=f"{win_rate:.1%} (minimum: {self.MIN_WIN_RATE:.1%}) - Too low",
                required_for_live=True,
            )
    
    def _validate_drawdown(self, metrics: AggregatedMetrics) -> ValidationResult:
        """Validate maximum drawdown."""
        drawdown = metrics.paper_trading.max_drawdown
        
        if drawdown >= self.MAX_DRAWDOWN_THRESHOLD:
            return ValidationResult(
                check_name="Maximum Drawdown",
                status="PASS",
                score=1.0,
                message=f"{drawdown:.1%} (threshold: {self.MAX_DRAWDOWN_THRESHOLD:.1%})",
                required_for_live=True,
            )
        elif drawdown >= self.MAX_DRAWDOWN_THRESHOLD * 1.2:
            return ValidationResult(
                check_name="Maximum Drawdown",
                status="WARNING",
                score=abs(drawdown / self.MAX_DRAWDOWN_THRESHOLD),
                message=f"{drawdown:.1%} (threshold: {self.MAX_DRAWDOWN_THRESHOLD:.1%}) - High drawdown",
                required_for_live=True,
            )
        else:
            return ValidationResult(
                check_name="Maximum Drawdown",
                status="FAIL",
                score=abs(drawdown / self.MAX_DRAWDOWN_THRESHOLD),
                message=f"{drawdown:.1%} (threshold: {self.MAX_DRAWDOWN_THRESHOLD:.1%}) - Excessive drawdown",
                required_for_live=True,
            )
    
    def _validate_fill_rate(self, metrics: AggregatedMetrics) -> ValidationResult:
        """Validate execution fill rate."""
        fill_rate = metrics.execution.fill_rate
        
        if fill_rate >= self.MIN_FILL_RATE:
            return ValidationResult(
                check_name="Execution Fill Rate",
                status="PASS",
                score=1.0,
                message=f"{fill_rate:.1%} (minimum: {self.MIN_FILL_RATE:.1%})",
                required_for_live=True,
            )
        elif fill_rate >= self.MIN_FILL_RATE * 0.95:
            return ValidationResult(
                check_name="Execution Fill Rate",
                status="WARNING",
                score=fill_rate / self.MIN_FILL_RATE,
                message=f"{fill_rate:.1%} (minimum: {self.MIN_FILL_RATE:.1%}) - Below target",
                required_for_live=True,
            )
        else:
            return ValidationResult(
                check_name="Execution Fill Rate",
                status="FAIL",
                score=fill_rate / self.MIN_FILL_RATE,
                message=f"{fill_rate:.1%} (minimum: {self.MIN_FILL_RATE:.1%}) - Too low",
                required_for_live=True,
            )
    
    def _validate_uptime(self, metrics: AggregatedMetrics) -> ValidationResult:
        """Validate infrastructure uptime."""
        uptime = metrics.infrastructure.uptime_percentage / 100.0
        
        if uptime >= self.MIN_UPTIME:
            return ValidationResult(
                check_name="Infrastructure Uptime",
                status="PASS",
                score=1.0,
                message=f"{uptime:.1%} (minimum: {self.MIN_UPTIME:.1%})",
                required_for_live=True,
            )
        elif uptime >= self.MIN_UPTIME * 0.95:
            return ValidationResult(
                check_name="Infrastructure Uptime",
                status="WARNING",
                score=uptime / self.MIN_UPTIME,
                message=f"{uptime:.1%} (minimum: {self.MIN_UPTIME:.1%}) - Below target",
                required_for_live=True,
            )
        else:
            return ValidationResult(
                check_name="Infrastructure Uptime",
                status="FAIL",
                score=uptime / self.MIN_UPTIME,
                message=f"{uptime:.1%} (minimum: {self.MIN_UPTIME:.1%}) - Unreliable",
                required_for_live=True,
            )
    
    def _validate_dashboard_sync(self, metrics: AggregatedMetrics) -> ValidationResult:
        """Validate dashboard synchronization health."""
        sync_health = metrics.infrastructure.dashboard_sync_health
        
        if sync_health >= self.MIN_DASHBOARD_SYNC:
            return ValidationResult(
                check_name="Dashboard Sync Health",
                status="PASS",
                score=1.0,
                message=f"{sync_health:.1%} (minimum: {self.MIN_DASHBOARD_SYNC:.1%})",
                required_for_live=False,  # Not blocking, but important
            )
        elif sync_health >= self.MIN_DASHBOARD_SYNC * 0.9:
            return ValidationResult(
                check_name="Dashboard Sync Health",
                status="WARNING",
                score=sync_health / self.MIN_DASHBOARD_SYNC,
                message=f"{sync_health:.1%} (minimum: {self.MIN_DASHBOARD_SYNC:.1%}) - Degraded",
                required_for_live=False,
            )
        else:
            return ValidationResult(
                check_name="Dashboard Sync Health",
                status="FAIL",
                score=sync_health / self.MIN_DASHBOARD_SYNC,
                message=f"{sync_health:.1%} (minimum: {self.MIN_DASHBOARD_SYNC:.1%}) - Poor sync",
                required_for_live=False,
            )
    
    def _validate_total_trades(self, metrics: AggregatedMetrics) -> ValidationResult:
        """Validate minimum number of trades."""
        MIN_TRADES = 50
        total_trades = metrics.paper_trading.total_trades
        
        if total_trades >= MIN_TRADES:
            return ValidationResult(
                check_name="Total Trades",
                status="PASS",
                score=1.0,
                message=f"{total_trades} trades (minimum: {MIN_TRADES})",
                required_for_live=True,
            )
        elif total_trades >= MIN_TRADES * 0.7:
            return ValidationResult(
                check_name="Total Trades",
                status="WARNING",
                score=total_trades / MIN_TRADES,
                message=f"{total_trades} trades (minimum: {MIN_TRADES}) - Low sample size",
                required_for_live=True,
            )
        else:
            return ValidationResult(
                check_name="Total Trades",
                status="FAIL",
                score=total_trades / MIN_TRADES,
                message=f"{total_trades} trades (minimum: {MIN_TRADES}) - Insufficient data",
                required_for_live=True,
            )
    
    def _compute_overall_status(
        self, results: list[ValidationResult]
    ) -> tuple[ValidationStatus, float, list[str], list[str]]:
        """Compute overall validation status."""
        blockers: list[str] = []
        warnings: list[str] = []
        
        # Check for blockers (required checks that failed)
        for result in results:
            if result.required_for_live and result.status == "FAIL":
                blockers.append(f"{result.check_name}: {result.message}")
            elif result.status == "WARNING":
                warnings.append(f"{result.check_name}: {result.message}")
        
        # Compute overall score (weighted average)
        total_score = sum(r.score for r in results)
        overall_score = total_score / len(results) if results else 0.0
        
        # Determine overall status
        if blockers:
            overall_status: ValidationStatus = "FAIL"
        elif warnings:
            overall_status = "WARNING"
        else:
            overall_status = "PASS"
        
        return overall_status, overall_score, blockers, warnings


# Global singleton instance
_validator = OperationalValidator()


def validate(metrics: AggregatedMetrics | None = None) -> OperationalValidation:
    """Convenience function to validate using the global validator."""
    return _validator.validate(metrics)
