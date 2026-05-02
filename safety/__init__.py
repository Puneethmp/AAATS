"""
Safety Lock System — Phase 10

This module provides comprehensive safety mechanisms for live trading deployment.
It integrates with existing foundation components (kill_switch, health_monitor)
and adds additional layers of protection.

Components:
- live_safety_lock: Multi-layer safety gate for live trading activation
- pre_trade_validator: Real-time validation before every trade
- emergency_protocols: Automated emergency response system
- safety_monitor: Continuous safety monitoring and alerting
"""

from safety.live_safety_lock import (
    LiveSafetyLock,
    SafetyLockDecision,
    SafetyLockStatus,
    check_safety_lock,
    get_safety_status,
)
from safety.pre_trade_validator import (
    PreTradeValidator,
    PreTradeValidation,
    ValidationResult,
)
from safety.emergency_protocols import (
    EmergencyProtocol,
    EmergencyAction,
    EmergencyLevel,
    trigger_emergency_protocol,
)
from safety.safety_monitor import (
    SafetyMonitor,
    SafetyAlert,
    SafetyMetrics,
)

__all__ = [
    # Live Safety Lock
    "LiveSafetyLock",
    "SafetyLockDecision",
    "SafetyLockStatus",
    "check_safety_lock",
    "get_safety_status",
    # Pre-Trade Validator
    "PreTradeValidator",
    "PreTradeValidation",
    "ValidationResult",
    # Emergency Protocols
    "EmergencyProtocol",
    "EmergencyAction",
    "EmergencyLevel",
    "trigger_emergency_protocol",
    # Safety Monitor
    "SafetyMonitor",
    "SafetyAlert",
    "SafetyMetrics",
]
