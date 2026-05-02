"""
Streamlit Sync Bridge — Connects Streamlit dashboard to backend state.

Provides high-level functions for the Streamlit dashboard to:
  - Read real-time state with automatic staleness detection
  - Display sync status indicators
  - Handle backend disconnection gracefully
  - Cache data efficiently to reduce file I/O

Architecture:
  - Wraps heartbeat_monitor, stale_data_detector, realtime_state_manager
  - Provides Streamlit-friendly data structures
  - Handles errors gracefully (returns safe defaults)
  - Includes built-in caching with TTL
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from foundation.logger import get_logger
from monitoring.heartbeat_monitor import get_all_heartbeats, get_heartbeat
from monitoring.realtime_state_manager import MarketState, get_all_states, get_state
from monitoring.stale_data_detector import StalenessReport, check_all_markets, check_staleness

_log = get_logger("monitoring", "streamlit_sync_bridge")


@dataclass
class DashboardSyncStatus:
    """Sync status for dashboard display."""
    is_connected: bool
    is_degraded: bool
    is_stale: bool
    status_emoji: str
    status_text: str
    warnings: list[str]
    heartbeat_age_seconds: float | None
    state_age_seconds: float | None


class StreamlitSyncBridge:
    """Bridge between backend state and Streamlit dashboard."""
    
    def __init__(self, cache_ttl_seconds: float = 5.0):
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, Any]] = {}  # key -> (timestamp, value)
    
    def _get_cached(self, key: str) -> Any | None:
        """Get cached value if still valid."""
        if key not in self._cache:
            return None
        
        timestamp, value = self._cache[key]
        age = time.time() - timestamp
        
        if age > self.cache_ttl_seconds:
            del self._cache[key]
            return None
        
        return value
    
    def _set_cached(self, key: str, value: Any) -> None:
        """Set cached value."""
        self._cache[key] = (time.time(), value)
    
    def get_sync_status(self, market: str) -> DashboardSyncStatus:
        """
        Get sync status for a specific market.
        
        Returns a DashboardSyncStatus with emoji, text, and warnings.
        """
        cache_key = f"sync_status_{market}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        # Check staleness
        staleness = check_staleness(market)
        
        # Get heartbeat age
        hb = get_heartbeat(market)
        heartbeat_age = staleness.heartbeat_age_seconds
        
        # Get state age
        from monitoring.realtime_state_manager import get_state_age
        state_age = get_state_age(market)
        
        # Determine status
        if staleness.is_disconnected:
            status = DashboardSyncStatus(
                is_connected=False,
                is_degraded=False,
                is_stale=True,
                status_emoji="🔴",
                status_text="DISCONNECTED",
                warnings=staleness.warnings,
                heartbeat_age_seconds=heartbeat_age,
                state_age_seconds=state_age,
            )
        elif staleness.is_stale:
            status = DashboardSyncStatus(
                is_connected=True,
                is_degraded=False,
                is_stale=True,
                status_emoji="🟠",
                status_text="STALE",
                warnings=staleness.warnings,
                heartbeat_age_seconds=heartbeat_age,
                state_age_seconds=state_age,
            )
        elif staleness.is_degraded:
            status = DashboardSyncStatus(
                is_connected=True,
                is_degraded=True,
                is_stale=False,
                status_emoji="🟡",
                status_text="DEGRADED",
                warnings=staleness.warnings,
                heartbeat_age_seconds=heartbeat_age,
                state_age_seconds=state_age,
            )
        else:
            status = DashboardSyncStatus(
                is_connected=True,
                is_degraded=False,
                is_stale=False,
                status_emoji="🟢",
                status_text="LIVE",
                warnings=[],
                heartbeat_age_seconds=heartbeat_age,
                state_age_seconds=state_age,
            )
        
        self._set_cached(cache_key, status)
        return status
    
    def get_all_sync_statuses(self) -> dict[str, DashboardSyncStatus]:
        """Get sync status for all markets."""
        markets = ["us", "india", "crypto"]
        return {market: self.get_sync_status(market) for market in markets}
    
    def get_market_state(self, market: str) -> MarketState | None:
        """
        Get real-time market state with caching.
        
        Returns None if state is unavailable or too stale.
        """
        cache_key = f"market_state_{market}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        state = get_state(market)
        
        if state:
            self._set_cached(cache_key, state)
        
        return state
    
    def get_all_market_states(self) -> dict[str, MarketState]:
        """Get all market states with caching."""
        states = get_all_states()
        
        # Cache each state
        for market, state in states.items():
            self._set_cached(f"market_state_{market}", state)
        
        return states
    
    def get_dashboard_summary(self) -> dict[str, Any]:
        """
        Get a complete dashboard summary with all sync info.
        
        Returns a dict suitable for Streamlit display.
        """
        cache_key = "dashboard_summary"
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        sync_statuses = self.get_all_sync_statuses()
        market_states = self.get_all_market_states()
        heartbeats = get_all_heartbeats()
        
        summary = {
            "sync_statuses": sync_statuses,
            "market_states": market_states,
            "heartbeats": heartbeats,
            "overall_status": self._compute_overall_status(sync_statuses),
        }
        
        self._set_cached(cache_key, summary)
        return summary
    
    def _compute_overall_status(self, sync_statuses: dict[str, DashboardSyncStatus]) -> str:
        """Compute overall system status from individual market statuses."""
        if not sync_statuses:
            return "UNKNOWN"
        
        if any(s.is_stale for s in sync_statuses.values()):
            return "STALE"
        
        if any(s.is_degraded for s in sync_statuses.values()):
            return "DEGRADED"
        
        if all(s.is_connected for s in sync_statuses.values()):
            return "LIVE"
        
        return "UNKNOWN"
    
    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        _log.debug("Cleared sync bridge cache")


# Global singleton instance
_bridge = StreamlitSyncBridge()


def get_sync_status(market: str) -> DashboardSyncStatus:
    """Convenience function to get sync status using the global bridge."""
    return _bridge.get_sync_status(market)


def get_all_sync_statuses() -> dict[str, DashboardSyncStatus]:
    """Convenience function to get all sync statuses using the global bridge."""
    return _bridge.get_all_sync_statuses()


def get_market_state(market: str) -> MarketState | None:
    """Convenience function to get market state using the global bridge."""
    return _bridge.get_market_state(market)


def get_all_market_states() -> dict[str, MarketState]:
    """Convenience function to get all market states using the global bridge."""
    return _bridge.get_all_market_states()


def get_dashboard_summary() -> dict[str, Any]:
    """Convenience function to get dashboard summary using the global bridge."""
    return _bridge.get_dashboard_summary()


def clear_cache() -> None:
    """Convenience function to clear cache using the global bridge."""
    _bridge.clear_cache()
