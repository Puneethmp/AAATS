"""
Production Readiness Module — Validates system readiness for live deployment.

This module provides comprehensive validation of the AAATS system before
allowing live trading deployment. It checks:
  - Paper trading performance and stability
  - Infrastructure health and reliability
  - Risk management effectiveness
  - Execution quality and consistency
  - Dashboard synchronization health
  - Recovery and resilience capabilities

The production readiness score (0-100%) determines whether the system
is ready for live deployment.
"""

__all__ = [
    "readiness_engine",
    "live_readiness_score",
    "deployment_gatekeeper",
    "operational_validator",
    "metrics_aggregator",
]
