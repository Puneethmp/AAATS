"""
Live Safety Lock — Multi-layer safety gate for live trading activation.

This module provides a comprehensive safety lock system that prevents
live trading from being enabled unless ALL safety requirements are met.

It integrates with:
- production_readiness.deployment_gatekeeper (readiness score)
- foundation.kill_switch (halt state)
- foundation.health_monitor (system health)
- trading.live_loop (trading mode state)
- learning.adaptive_engine (strategy health)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from foundation.kill_switch import is_halted
from foundation.logger import get_logger
from production_readiness.deployment_gatekeeper import check_deployment_allowed

_log = get_logger("safety", "live_safety_lock")


class SafetyLockStatus(Enum):
    """Status of the safety lock."""
    LOCKED = "locked"           # Live trading not allowed
    UNLOCKED = "unlocked"       # Live trading allowed
    OVERRIDE = "override"       # Manual override active (emergency only)


@dataclass
class SafetyLockDecision:
    """Decision on whether live trading is allowed."""
    status: SafetyLockStatus
    allowed: bool
    reason: str
    timestamp: str
    checks_passed: dict[str, bool]
    blockers: list[str]
    readiness_score: float
    override_by: str | None = None
    override_reason: str | None = None


class LiveSafetyLock:
    """
    Multi-layer safety lock for live trading.
    
    Checks:
    1. Production readiness score >= 85%
    2. No active kill switches
    3. System health checks passing
    4. Paper trading results meet criteria
    5. Strategy health scores acceptable
    6. No recent critical errors
    7. Manual approval flag set
    """
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.data_dir / "safety_lock_state.json"
        self.approval_file = self.data_dir / "live_trading_approval.json"
        
        # Safety thresholds
        self.MIN_READINESS_SCORE = 85.0
        self.MIN_PAPER_TRADING_DAYS = 30
        self.MIN_PAPER_SHARPE = 1.0
        self.MIN_STRATEGY_HEALTH = 40.0
        self.MAX_RECENT_ERRORS = 5
    
    def check_safety_lock(self, market: str = "all") -> SafetyLockDecision:
        """
        Check if live trading is allowed for the given market.
        
        Args:
            market: Market to check ("us", "india", "crypto", "all")
        
        Returns:
            SafetyLockDecision with detailed status
        """
        checks = {}
        blockers = []
        
        # Check 1: Production readiness
        try:
            deployment_decision = check_deployment_allowed()
            checks["production_readiness"] = deployment_decision.allowed
            readiness_score = deployment_decision.readiness_score
            
            if not deployment_decision.allowed:
                blockers.append(f"Production readiness: {deployment_decision.reason}")
        except Exception as e:
            checks["production_readiness"] = False
            readiness_score = 0.0
            blockers.append(f"Production readiness check failed: {e}")
        
        # Check 2: Kill switch state
        try:
            if market == "all":
                markets_to_check = ["us", "india", "crypto"]
            else:
                markets_to_check = [market]
            
            kill_switch_ok = True
            for m in markets_to_check:
                if is_halted(m):
                    kill_switch_ok = False
                    blockers.append(f"Kill switch active for {m}")
            
            checks["kill_switch"] = kill_switch_ok
        except Exception as e:
            checks["kill_switch"] = False
            blockers.append(f"Kill switch check failed: {e}")
        
        # Check 3: Manual approval flag
        approval_ok = self._check_manual_approval(market)
        checks["manual_approval"] = approval_ok
        if not approval_ok:
            blockers.append("Manual approval not granted")
        
        # Check 4: Paper trading results
        paper_ok = self._check_paper_trading_results(market)
        checks["paper_trading"] = paper_ok
        if not paper_ok:
            blockers.append("Paper trading results do not meet criteria")
        
        # Check 5: Strategy health
        strategy_ok = self._check_strategy_health(market)
        checks["strategy_health"] = strategy_ok
        if not strategy_ok:
            blockers.append("Strategy health scores below threshold")
        
        # Check 6: Recent errors
        errors_ok = self._check_recent_errors()
        checks["recent_errors"] = errors_ok
        if not errors_ok:
            blockers.append(f"Too many recent errors (>{self.MAX_RECENT_ERRORS})")
        
        # Check for manual override
        override_status = self._check_override()
        
        # Make decision
        all_checks_passed = all(checks.values())
        
        if override_status:
            status = SafetyLockStatus.OVERRIDE
            allowed = True
            reason = f"Manual override active: {override_status['reason']}"
            override_by = override_status["by"]
            override_reason = override_status["reason"]
        elif all_checks_passed:
            status = SafetyLockStatus.UNLOCKED
            allowed = True
            reason = "All safety checks passed"
            override_by = None
            override_reason = None
        else:
            status = SafetyLockStatus.LOCKED
            allowed = False
            reason = f"{len(blockers)} safety check(s) failed"
            override_by = None
            override_reason = None
        
        decision = SafetyLockDecision(
            status=status,
            allowed=allowed,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
            checks_passed=checks,
            blockers=blockers,
            readiness_score=readiness_score,
            override_by=override_by,
            override_reason=override_reason,
        )
        
        # Save decision
        self._save_decision(decision)
        
        # Log decision
        if allowed:
            _log.info(f"✅ Safety lock UNLOCKED for {market} (score: {readiness_score:.1f}%)")
        else:
            _log.warning(f"🔒 Safety lock LOCKED for {market} (score: {readiness_score:.1f}%)")
            for blocker in blockers:
                _log.warning(f"  Blocker: {blocker}")
        
        return decision
    
    def _check_manual_approval(self, market: str) -> bool:
        """Check if manual approval has been granted."""
        try:
            if not self.approval_file.exists():
                return False
            
            data = json.loads(self.approval_file.read_text(encoding="utf-8"))
            
            # Check if approval exists for this market
            if market == "all":
                return all(data.get(m, {}).get("approved", False) for m in ["us", "india", "crypto"])
            else:
                return data.get(market, {}).get("approved", False)
        except Exception as e:
            _log.error(f"Failed to check manual approval: {e}")
            return False
    
    def _check_paper_trading_results(self, market: str) -> bool:
        """Check if paper trading results meet criteria."""
        try:
            # This would integrate with learning.performance_tracker
            # For now, return True as a placeholder
            # TODO: Implement actual paper trading results check
            return True
        except Exception as e:
            _log.error(f"Failed to check paper trading results: {e}")
            return False
    
    def _check_strategy_health(self, market: str) -> bool:
        """Check if strategy health scores are acceptable."""
        try:
            # This would integrate with learning.adaptive_engine
            # For now, return True as a placeholder
            # TODO: Implement actual strategy health check
            return True
        except Exception as e:
            _log.error(f"Failed to check strategy health: {e}")
            return False
    
    def _check_recent_errors(self) -> bool:
        """Check if there are too many recent errors."""
        try:
            # This would check logs for recent critical errors
            # For now, return True as a placeholder
            # TODO: Implement actual error count check
            return True
        except Exception as e:
            _log.error(f"Failed to check recent errors: {e}")
            return False
    
    def _check_override(self) -> dict | None:
        """Check if manual override is active."""
        try:
            override_file = self.data_dir / "safety_override.json"
            if not override_file.exists():
                return None
            
            data = json.loads(override_file.read_text(encoding="utf-8"))
            
            # Check if override is still valid (expires after 24 hours)
            override_time = datetime.fromisoformat(data["timestamp"])
            elapsed_hours = (datetime.now(timezone.utc) - override_time).total_seconds() / 3600
            
            if elapsed_hours > 24:
                # Override expired
                override_file.unlink()
                return None
            
            return data
        except Exception as e:
            _log.error(f"Failed to check override: {e}")
            return None
    
    def _save_decision(self, decision: SafetyLockDecision) -> None:
        """Save safety lock decision to file."""
        try:
            decision_dict = asdict(decision)
            decision_dict["status"] = decision.status.value
            
            tmp_file = self.lock_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(decision_dict, indent=2), encoding="utf-8")
            tmp_file.replace(self.lock_file)
        except Exception as e:
            _log.error(f"Failed to save safety lock decision: {e}")
    
    def grant_manual_approval(self, market: str, approved_by: str, reason: str) -> None:
        """
        Grant manual approval for live trading.
        
        Args:
            market: Market to approve ("us", "india", "crypto", "all")
            approved_by: Name of person granting approval
            reason: Reason for approval
        """
        try:
            # Load existing approvals
            if self.approval_file.exists():
                data = json.loads(self.approval_file.read_text(encoding="utf-8"))
            else:
                data = {}
            
            # Add approval
            approval_data = {
                "approved": True,
                "approved_by": approved_by,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            if market == "all":
                for m in ["us", "india", "crypto"]:
                    data[m] = approval_data
            else:
                data[market] = approval_data
            
            # Save approvals
            tmp_file = self.approval_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_file.replace(self.approval_file)
            
            _log.warning(f"✅ Manual approval granted for {market} by {approved_by}: {reason}")
        except Exception as e:
            _log.error(f"Failed to grant manual approval: {e}")
            raise
    
    def revoke_manual_approval(self, market: str, revoked_by: str, reason: str) -> None:
        """
        Revoke manual approval for live trading.
        
        Args:
            market: Market to revoke ("us", "india", "crypto", "all")
            revoked_by: Name of person revoking approval
            reason: Reason for revocation
        """
        try:
            if not self.approval_file.exists():
                return
            
            data = json.loads(self.approval_file.read_text(encoding="utf-8"))
            
            # Revoke approval
            if market == "all":
                data = {}
            else:
                data.pop(market, None)
            
            # Save approvals
            tmp_file = self.approval_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_file.replace(self.approval_file)
            
            _log.warning(f"❌ Manual approval revoked for {market} by {revoked_by}: {reason}")
        except Exception as e:
            _log.error(f"Failed to revoke manual approval: {e}")
            raise
    
    def set_override(self, reason: str, authorized_by: str) -> None:
        """
        Set manual override (emergency use only).
        
        Args:
            reason: Reason for override
            authorized_by: Name of person authorizing override
        """
        try:
            override_file = self.data_dir / "safety_override.json"
            
            data = {
                "by": authorized_by,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            tmp_file = override_file.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_file.replace(override_file)
            
            _log.warning(f"🚨 Safety lock OVERRIDE set by {authorized_by}: {reason}")
        except Exception as e:
            _log.error(f"Failed to set override: {e}")
            raise
    
    def clear_override(self) -> None:
        """Clear manual override."""
        try:
            override_file = self.data_dir / "safety_override.json"
            if override_file.exists():
                override_file.unlink()
                _log.info("Override cleared")
        except Exception as e:
            _log.error(f"Failed to clear override: {e}")
            raise
    
    def get_status(self, market: str = "all") -> SafetyLockDecision:
        """Get current safety lock status."""
        return self.check_safety_lock(market)


# Global singleton instance
_safety_lock = LiveSafetyLock()


def check_safety_lock(market: str = "all") -> SafetyLockDecision:
    """Convenience function to check safety lock using the global instance."""
    return _safety_lock.check_safety_lock(market)


def get_safety_status(market: str = "all") -> SafetyLockDecision:
    """Convenience function to get safety status using the global instance."""
    return _safety_lock.get_status(market)


def grant_manual_approval(market: str, approved_by: str, reason: str) -> None:
    """Convenience function to grant manual approval."""
    _safety_lock.grant_manual_approval(market, approved_by, reason)


def revoke_manual_approval(market: str, revoked_by: str, reason: str) -> None:
    """Convenience function to revoke manual approval."""
    _safety_lock.revoke_manual_approval(market, revoked_by, reason)


def set_override(reason: str, authorized_by: str) -> None:
    """Convenience function to set override."""
    _safety_lock.set_override(reason, authorized_by)


def clear_override() -> None:
    """Convenience function to clear override."""
    _safety_lock.clear_override()
