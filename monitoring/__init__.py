"""
Real-time monitoring and synchronization layer for AAATS.

This module provides the infrastructure for real-time dashboard synchronization,
heartbeat monitoring, stale data detection, and backend-to-frontend state bridging.
"""

__all__ = [
    "heartbeat_monitor",
    "stale_data_detector",
    "realtime_state_manager",
    "streamlit_sync_bridge",
    "dashboard_cache_manager",
]
