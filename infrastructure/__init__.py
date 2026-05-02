"""
Infrastructure module for AAATS Phase 4: Self-Healing & Operational Resilience.

Provides:
- Process locking to prevent duplicate execution
- Watchdog/recovery mechanisms
- Crash recovery with state persistence
- API reconnection logic
- Health check utilities
"""

from infrastructure.api_reconnector import (
    APIReconnector,
    MultiAPIReconnector,
    ReconnectConfig,
)
from infrastructure.process_lock import ProcessLock
from infrastructure.state_checkpoint import StateCheckpoint, TradingCheckpoint
from infrastructure.watchdog import ProcessConfig, Watchdog

__all__ = [
    "ProcessLock",
    "Watchdog",
    "ProcessConfig",
    "StateCheckpoint",
    "TradingCheckpoint",
    "APIReconnector",
    "MultiAPIReconnector",
    "ReconnectConfig",
]
