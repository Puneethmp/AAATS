"""
Deployment Gatekeeper — Prevents live deployment if system is not ready.

This module acts as a hard gate that prevents live trading from being
enabled unless all production readiness requirements are met.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from foundation.logger import get_logger
from production_readiness.live_readiness_score import ReadinessScore, compute_score

_log = get_logger("production_readiness", "deployment_gatekeeper")


@dataclass
class DeploymentDecision:
    """Decision on whether to allow live deployment."""
    allowed: bool
    reason: str
    readiness_score: float
    timestamp: str
    blockers: list[str]


class DeploymentGatekeeper:
    """Controls access to live trading deployment."""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.decision_file = self.data_dir / "deployment_decision.json"
    
    def check_deployment_allowed(self) -> DeploymentDecision:
        """
        Check if live deployment is allowed.
        
        Returns:
            DeploymentDecision with allowed status and reason
        """
        try:
            # Compute readiness score
            score = compute_score()
            
            # Make decision
            if score.is_ready_for_live:
                decision = DeploymentDecision(
                    allowed=True,
                    reason="All production readiness requirements met",
                    readiness_score=score.overall_percentage,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    blockers=[],
                )
            else:
                decision = DeploymentDecision(
                    allowed=False,
                    reason=score.recommendation,
                    readiness_score=score.overall_percentage,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    blockers=score.blockers,
                )
            
            # Save decision
            self._save_decision(decision)
            
            # Log decision
            if decision.allowed:
                _log.info(f"✅ Live deployment ALLOWED (score: {decision.readiness_score:.1f}%)")
            else:
                _log.warning(f"❌ Live deployment BLOCKED (score: {decision.readiness_score:.1f}%)")
                for blocker in decision.blockers:
                    _log.warning(f"  Blocker: {blocker}")
            
            return decision
        
        except Exception as e:
            _log.error(f"Failed to check deployment: {e}")
            return DeploymentDecision(
                allowed=False,
                reason=f"Error checking readiness: {e}",
                readiness_score=0.0,
                timestamp=datetime.now(timezone.utc).isoformat(),
                blockers=["System error during readiness check"],
            )
    
    def _save_decision(self, decision: DeploymentDecision) -> None:
        """Save deployment decision to file."""
        try:
            decision_dict = asdict(decision)
            tmp_file = self.decision_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(decision_dict, indent=2), encoding="utf-8")
            tmp_file.replace(self.decision_file)
        except Exception as e:
            _log.error(f"Failed to save deployment decision: {e}")
    
    def get_last_decision(self) -> DeploymentDecision | None:
        """Get the last deployment decision."""
        try:
            if not self.decision_file.exists():
                return None
            
            data = json.loads(self.decision_file.read_text(encoding="utf-8"))
            return DeploymentDecision(**data)
        except Exception as e:
            _log.error(f"Failed to read deployment decision: {e}")
            return None
    
    def force_block_deployment(self, reason: str) -> None:
        """
        Force block live deployment (emergency use only).
        
        Args:
            reason: Reason for blocking deployment
        """
        decision = DeploymentDecision(
            allowed=False,
            reason=f"FORCE BLOCKED: {reason}",
            readiness_score=0.0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            blockers=[reason],
        )
        self._save_decision(decision)
        _log.warning(f"🚨 Live deployment FORCE BLOCKED: {reason}")


# Global singleton instance
_gatekeeper = DeploymentGatekeeper()


def check_deployment_allowed() -> DeploymentDecision:
    """Convenience function to check deployment using the global gatekeeper."""
    return _gatekeeper.check_deployment_allowed()


def get_last_decision() -> DeploymentDecision | None:
    """Convenience function to get last decision using the global gatekeeper."""
    return _gatekeeper.get_last_decision()


def force_block_deployment(reason: str) -> None:
    """Convenience function to force block deployment using the global gatekeeper."""
    _gatekeeper.force_block_deployment(reason)
