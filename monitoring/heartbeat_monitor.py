"""
Heartbeat Monitor — Backend service that emits periodic heartbeats.

The paper trading loop and other autonomous services call emit_heartbeat()
every 15-30 seconds to signal they are alive. The Streamlit dashboard reads
these heartbeats to detect backend connectivity issues.

Architecture:
  - Writes to data/heartbeat.json (atomic file replacement)
  - Includes: timestamp, market, status, cycle_count, error (if any)
  - Dashboard reads this file to detect stale backend state
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from foundation.logger import get_logger

_log = get_logger("monitoring", "heartbeat_monitor")

Status = Literal["RUNNING", "IDLE", "HALTED", "ERROR", "MARKET_CLOSED"]


@dataclass
class Heartbeat:
    """Single heartbeat record."""
    timestamp: str
    market: str
    status: Status
    cycle_count: int
    error: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)


class HeartbeatMonitor:
    """Manages heartbeat emission and persistence."""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path = self.data_dir / "heartbeat.json"
        self._last_emit: dict[str, float] = {}  # market -> timestamp
    
    def emit_heartbeat(
        self,
        market: str,
        status: Status,
        cycle_count: int,
        error: str = "",
        min_interval_seconds: float = 15.0,
    ) -> bool:
        """
        Emit a heartbeat for the given market.
        
        Args:
            market: Market identifier (us, india, crypto)
            status: Current status
            cycle_count: Number of cycles completed
            error: Error message if status is ERROR
            min_interval_seconds: Minimum time between heartbeats (rate limiting)
        
        Returns:
            True if heartbeat was emitted, False if rate-limited
        """
        now = time.time()
        last = self._last_emit.get(market, 0.0)
        
        # Rate limiting: don't emit more frequently than min_interval
        if now - last < min_interval_seconds and status != "ERROR":
            return False
        
        heartbeat = Heartbeat(
            timestamp=datetime.now(timezone.utc).isoformat(),
            market=market,
            status=status,
            cycle_count=cycle_count,
            error=error,
        )
        
        try:
            # Read existing heartbeats
            if self.heartbeat_path.exists():
                data = json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
            else:
                data = {}
            
            # Update this market's heartbeat
            data[market] = heartbeat.to_dict()
            
            # Atomic write (write to temp file, then replace)
            tmp_path = self.heartbeat_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(self.heartbeat_path)
            
            self._last_emit[market] = now
            
            if status == "ERROR":
                _log.error(f"Heartbeat [{market}] ERROR: {error}")
            else:
                _log.debug(f"Heartbeat [{market}] {status} cycle={cycle_count}")
            
            return True
        
        except Exception as e:
            _log.error(f"Failed to emit heartbeat for {market}: {e}")
            return False
    
    def get_heartbeat(self, market: str) -> Heartbeat | None:
        """Read the latest heartbeat for a specific market."""
        try:
            if not self.heartbeat_path.exists():
                return None
            
            data = json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
            hb_data = data.get(market)
            
            if not hb_data:
                return None
            
            return Heartbeat(**hb_data)
        
        except Exception as e:
            _log.error(f"Failed to read heartbeat for {market}: {e}")
            return None
    
    def get_all_heartbeats(self) -> dict[str, Heartbeat]:
        """Read all heartbeats."""
        try:
            if not self.heartbeat_path.exists():
                return {}
            
            data = json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
            return {
                market: Heartbeat(**hb_data)
                for market, hb_data in data.items()
            }
        
        except Exception as e:
            _log.error(f"Failed to read heartbeats: {e}")
            return {}
    
    def is_alive(self, market: str, max_age_seconds: float = 120.0) -> bool:
        """
        Check if a market's backend is alive.
        
        Args:
            market: Market identifier
            max_age_seconds: Maximum age of heartbeat before considering dead
        
        Returns:
            True if heartbeat exists and is recent, False otherwise
        """
        hb = self.get_heartbeat(market)
        if not hb:
            return False
        
        try:
            hb_time = datetime.fromisoformat(hb.timestamp)
            if hb_time.tzinfo is None:
                hb_time = hb_time.replace(tzinfo=timezone.utc)
            
            age = (datetime.now(timezone.utc) - hb_time).total_seconds()
            return age < max_age_seconds and hb.status != "ERROR"
        
        except Exception:
            return False


# Global singleton instance
_monitor = HeartbeatMonitor()


def emit_heartbeat(
    market: str,
    status: Status,
    cycle_count: int,
    error: str = "",
    min_interval_seconds: float = 15.0,
) -> bool:
    """Convenience function to emit a heartbeat using the global monitor."""
    return _monitor.emit_heartbeat(market, status, cycle_count, error, min_interval_seconds)


def get_heartbeat(market: str) -> Heartbeat | None:
    """Convenience function to get a heartbeat using the global monitor."""
    return _monitor.get_heartbeat(market)


def get_all_heartbeats() -> dict[str, Heartbeat]:
    """Convenience function to get all heartbeats using the global monitor."""
    return _monitor.get_all_heartbeats()


def is_alive(market: str, max_age_seconds: float = 120.0) -> bool:
    """Convenience function to check if a market is alive using the global monitor."""
    return _monitor.is_alive(market, max_age_seconds)
