"""
Real-Time State Manager — Manages shared state between backend and dashboard.

Provides a lightweight, file-based state cache that allows the paper trading
loop to publish state updates and the Streamlit dashboard to read them with
minimal latency.

Architecture:
  - Uses JSON files in data/state/ directory
  - Atomic writes (write to .tmp, then replace)
  - Separate files per market for isolation
  - Includes: positions, portfolio metrics, active signals, regime
  - Dashboard reads these files instead of querying SQLite repeatedly
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from foundation.logger import get_logger

_log = get_logger("monitoring", "realtime_state_manager")


@dataclass
class PositionSnapshot:
    """Snapshot of a single position."""
    symbol: str
    shares: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    entry_time: str


@dataclass
class MarketState:
    """Real-time state for a single market."""
    market: str
    timestamp: str
    regime: str
    portfolio_value: float
    cash: float
    positions: list[PositionSnapshot] = field(default_factory=list)
    active_signals: list[str] = field(default_factory=list)
    cycle_count: int = 0
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    open_position_count: int = 0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        return d


class RealtimeStateManager:
    """Manages real-time state cache."""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.state_dir = self.data_dir / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._last_write: dict[str, float] = {}  # market -> timestamp
    
    def _state_path(self, market: str) -> Path:
        """Get the state file path for a market."""
        return self.state_dir / f"{market}_state.json"
    
    def publish_state(
        self,
        state: MarketState,
        min_interval_seconds: float = 5.0,
    ) -> bool:
        """
        Publish a state update for a market.
        
        Args:
            state: MarketState to publish
            min_interval_seconds: Minimum time between publishes (rate limiting)
        
        Returns:
            True if state was published, False if rate-limited
        """
        now = time.time()
        last = self._last_write.get(state.market, 0.0)
        
        # Rate limiting: don't publish more frequently than min_interval
        if now - last < min_interval_seconds:
            return False
        
        try:
            state_path = self._state_path(state.market)
            
            # Atomic write
            tmp_path = state_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
            tmp_path.replace(state_path)
            
            self._last_write[state.market] = now
            
            _log.debug(
                f"Published state [{state.market}] "
                f"positions={state.open_position_count} "
                f"pnl={state.total_pnl:.2f} "
                f"regime={state.regime}"
            )
            
            return True
        
        except Exception as e:
            _log.error(f"Failed to publish state for {state.market}: {e}")
            return False
    
    def get_state(self, market: str) -> MarketState | None:
        """Read the latest state for a specific market."""
        try:
            state_path = self._state_path(market)
            
            if not state_path.exists():
                return None
            
            data = json.loads(state_path.read_text(encoding="utf-8"))
            
            # Reconstruct positions
            positions = [
                PositionSnapshot(**pos_data)
                for pos_data in data.get("positions", [])
            ]
            
            # Reconstruct MarketState
            state = MarketState(
                market=data["market"],
                timestamp=data["timestamp"],
                regime=data["regime"],
                portfolio_value=data["portfolio_value"],
                cash=data["cash"],
                positions=positions,
                active_signals=data.get("active_signals", []),
                cycle_count=data.get("cycle_count", 0),
                total_pnl=data.get("total_pnl", 0.0),
                daily_pnl=data.get("daily_pnl", 0.0),
                open_position_count=data.get("open_position_count", 0),
            )
            
            return state
        
        except Exception as e:
            _log.error(f"Failed to read state for {market}: {e}")
            return None
    
    def get_all_states(self) -> dict[str, MarketState]:
        """Read all market states."""
        states = {}
        
        for state_file in self.state_dir.glob("*_state.json"):
            market = state_file.stem.replace("_state", "")
            state = self.get_state(market)
            if state:
                states[market] = state
        
        return states
    
    def get_state_age(self, market: str) -> float | None:
        """
        Get the age of the state in seconds.
        
        Returns None if state doesn't exist or timestamp is invalid.
        """
        state = self.get_state(market)
        if not state:
            return None
        
        try:
            state_time = datetime.fromisoformat(state.timestamp)
            if state_time.tzinfo is None:
                state_time = state_time.replace(tzinfo=timezone.utc)
            
            age = (datetime.now(timezone.utc) - state_time).total_seconds()
            return age
        
        except Exception:
            return None
    
    def is_state_fresh(self, market: str, max_age_seconds: float = 60.0) -> bool:
        """Check if state is fresh (recent)."""
        age = self.get_state_age(market)
        return age is not None and age < max_age_seconds


# Global singleton instance
_manager = RealtimeStateManager()


def publish_state(state: MarketState, min_interval_seconds: float = 5.0) -> bool:
    """Convenience function to publish state using the global manager."""
    return _manager.publish_state(state, min_interval_seconds)


def get_state(market: str) -> MarketState | None:
    """Convenience function to get state using the global manager."""
    return _manager.get_state(market)


def get_all_states() -> dict[str, MarketState]:
    """Convenience function to get all states using the global manager."""
    return _manager.get_all_states()


def get_state_age(market: str) -> float | None:
    """Convenience function to get state age using the global manager."""
    return _manager.get_state_age(market)


def is_state_fresh(market: str, max_age_seconds: float = 60.0) -> bool:
    """Convenience function to check state freshness using the global manager."""
    return _manager.is_state_fresh(market, max_age_seconds)
