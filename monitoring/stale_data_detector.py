"""
Stale Data Detector — Detects when dashboard data is out of sync with backend.

Used by the Streamlit dashboard to display warnings when:
  - Heartbeat is too old
  - Last trade is stale
  - Database hasn't been updated recently
  - Backend appears disconnected

Architecture:
  - Reads heartbeat.json and various SQLite DBs
  - Computes staleness metrics
  - Returns structured warnings for UI display
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from foundation.logger import get_logger
from monitoring.heartbeat_monitor import get_heartbeat

_log = get_logger("monitoring", "stale_data_detector")

StalenessLevel = Literal["OK", "DEGRADED", "STALE", "DISCONNECTED"]


@dataclass
class StalenessReport:
    """Report on data staleness for a specific market."""
    market: str
    level: StalenessLevel
    heartbeat_age_seconds: float | None
    last_trade_age_seconds: float | None
    last_db_write_age_seconds: float | None
    warnings: list[str]
    is_backend_alive: bool
    
    @property
    def is_ok(self) -> bool:
        return self.level == "OK"
    
    @property
    def is_degraded(self) -> bool:
        return self.level == "DEGRADED"
    
    @property
    def is_stale(self) -> bool:
        return self.level == "STALE"
    
    @property
    def is_disconnected(self) -> bool:
        return self.level == "DISCONNECTED"


class StaleDataDetector:
    """Detects stale data conditions."""
    
    def __init__(
        self,
        data_dir: str = "data",
        heartbeat_warning_seconds: float = 60.0,
        heartbeat_stale_seconds: float = 120.0,
        trade_warning_seconds: float = 3600.0,  # 1 hour
        db_warning_seconds: float = 300.0,  # 5 minutes
    ):
        self.data_dir = Path(data_dir)
        self.heartbeat_warning_seconds = heartbeat_warning_seconds
        self.heartbeat_stale_seconds = heartbeat_stale_seconds
        self.trade_warning_seconds = trade_warning_seconds
        self.db_warning_seconds = db_warning_seconds
    
    def check_staleness(self, market: str) -> StalenessReport:
        """
        Check staleness for a specific market.
        
        Returns a StalenessReport with level and warnings.
        """
        warnings: list[str] = []
        now = datetime.now(timezone.utc)
        
        # Check heartbeat age
        heartbeat_age: float | None = None
        is_backend_alive = False
        
        hb = get_heartbeat(market)
        if hb:
            try:
                hb_time = datetime.fromisoformat(hb.timestamp)
                if hb_time.tzinfo is None:
                    hb_time = hb_time.replace(tzinfo=timezone.utc)
                heartbeat_age = (now - hb_time).total_seconds()
                is_backend_alive = heartbeat_age < self.heartbeat_stale_seconds
            except Exception as e:
                warnings.append(f"Invalid heartbeat timestamp: {e}")
        else:
            warnings.append("No heartbeat found")
        
        # Check last trade age
        last_trade_age: float | None = None
        paper_db = self.data_dir / "paper_trades.db"
        
        if paper_db.exists():
            try:
                conn = sqlite3.connect(str(paper_db), check_same_thread=False)
                row = conn.execute(
                    "SELECT timestamp FROM paper_trades WHERE market=? "
                    "ORDER BY timestamp DESC LIMIT 1",
                    (market,)
                ).fetchone()
                conn.close()
                
                if row and row[0]:
                    trade_time = datetime.fromisoformat(row[0])
                    if trade_time.tzinfo is None:
                        trade_time = trade_time.replace(tzinfo=timezone.utc)
                    last_trade_age = (now - trade_time).total_seconds()
            except Exception as e:
                warnings.append(f"Failed to check last trade: {e}")
        
        # Check last DB write age (using paper_trades.db mtime)
        last_db_write_age: float | None = None
        if paper_db.exists():
            try:
                mtime = paper_db.stat().st_mtime
                last_db_write_age = time.time() - mtime
            except Exception as e:
                warnings.append(f"Failed to check DB write time: {e}")
        
        # Determine staleness level
        level: StalenessLevel = "OK"
        
        if not is_backend_alive:
            level = "DISCONNECTED"
            warnings.append(f"Backend disconnected (heartbeat age: {heartbeat_age:.0f}s)" if heartbeat_age else "Backend disconnected (no heartbeat)")
        elif heartbeat_age and heartbeat_age > self.heartbeat_warning_seconds:
            level = "DEGRADED"
            warnings.append(f"Heartbeat is {heartbeat_age:.0f}s old (warning threshold: {self.heartbeat_warning_seconds:.0f}s)")
        elif last_db_write_age and last_db_write_age > self.db_warning_seconds:
            level = "DEGRADED"
            warnings.append(f"Database not updated for {last_db_write_age:.0f}s")
        
        # Additional warnings (don't change level, just inform)
        if last_trade_age and last_trade_age > self.trade_warning_seconds:
            warnings.append(f"No trades for {last_trade_age / 3600:.1f} hours (may be normal during low-volatility periods)")
        
        return StalenessReport(
            market=market,
            level=level,
            heartbeat_age_seconds=heartbeat_age,
            last_trade_age_seconds=last_trade_age,
            last_db_write_age_seconds=last_db_write_age,
            warnings=warnings,
            is_backend_alive=is_backend_alive,
        )
    
    def check_all_markets(self) -> dict[str, StalenessReport]:
        """Check staleness for all known markets."""
        markets = ["us", "india", "crypto"]
        return {market: self.check_staleness(market) for market in markets}


# Global singleton instance
_detector = StaleDataDetector()


def check_staleness(market: str) -> StalenessReport:
    """Convenience function to check staleness using the global detector."""
    return _detector.check_staleness(market)


def check_all_markets() -> dict[str, StalenessReport]:
    """Convenience function to check all markets using the global detector."""
    return _detector.check_all_markets()
