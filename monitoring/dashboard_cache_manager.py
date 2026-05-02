"""
Dashboard Cache Manager — Manages persistent cache for Streamlit dashboard.

Provides intelligent caching for expensive operations like:
  - Trade history aggregations
  - Equity curve calculations
  - Strategy performance breakdowns
  - Monthly returns

Architecture:
  - Uses SQLite as cache backend (data/dashboard_cache.db)
  - Automatic cache invalidation based on source data changes
  - TTL-based expiration
  - Cache warming for frequently accessed data
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from foundation.logger import get_logger

_log = get_logger("monitoring", "dashboard_cache_manager")


@dataclass
class CacheEntry:
    """A single cache entry."""
    key: str
    value: str  # JSON-serialized
    created_at: float
    expires_at: float
    source_hash: str  # Hash of source data for invalidation


class DashboardCacheManager:
    """Manages dashboard data cache."""
    
    def __init__(self, data_dir: str = "data", default_ttl_seconds: float = 60.0):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_db = self.data_dir / "dashboard_cache.db"
        self.default_ttl_seconds = default_ttl_seconds
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize cache database."""
        conn = sqlite3.connect(str(self.cache_db), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                source_hash TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expires_at ON cache(expires_at)")
        conn.commit()
        conn.close()
    
    def _compute_hash(self, data: Any) -> str:
        """Compute hash of data for cache invalidation."""
        if isinstance(data, (str, bytes)):
            content = data if isinstance(data, bytes) else data.encode()
        else:
            content = json.dumps(data, sort_keys=True).encode()
        
        return hashlib.sha256(content).hexdigest()[:16]
    
    def get(self, key: str, source_data: Any = None) -> Any | None:
        """
        Get cached value.
        
        Args:
            key: Cache key
            source_data: Source data for invalidation check (optional)
        
        Returns:
            Cached value if valid, None otherwise
        """
        try:
            conn = sqlite3.connect(str(self.cache_db), check_same_thread=False)
            row = conn.execute(
                "SELECT value, expires_at, source_hash FROM cache WHERE key=?",
                (key,)
            ).fetchone()
            conn.close()
            
            if not row:
                return None
            
            value_json, expires_at, cached_source_hash = row
            
            # Check expiration
            if time.time() > expires_at:
                self.delete(key)
                return None
            
            # Check source data invalidation
            if source_data is not None:
                current_hash = self._compute_hash(source_data)
                if current_hash != cached_source_hash:
                    self.delete(key)
                    return None
            
            # Deserialize and return
            value = json.loads(value_json)
            _log.debug(f"Cache HIT: {key}")
            return value
        
        except Exception as e:
            _log.error(f"Cache GET error for {key}: {e}")
            return None
    
    def set(
        self,
        key: str,
        value: Any,
        source_data: Any = None,
        ttl_seconds: float | None = None,
    ) -> bool:
        """
        Set cached value.
        
        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable)
            source_data: Source data for invalidation tracking (optional)
            ttl_seconds: Time-to-live in seconds (uses default if None)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
            now = time.time()
            expires_at = now + ttl
            
            value_json = json.dumps(value)
            source_hash = self._compute_hash(source_data) if source_data is not None else ""
            
            conn = sqlite3.connect(str(self.cache_db), check_same_thread=False)
            conn.execute(
                "INSERT OR REPLACE INTO cache (key, value, created_at, expires_at, source_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, value_json, now, expires_at, source_hash)
            )
            conn.commit()
            conn.close()
            
            _log.debug(f"Cache SET: {key} (ttl={ttl:.0f}s)")
            return True
        
        except Exception as e:
            _log.error(f"Cache SET error for {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """Delete a cache entry."""
        try:
            conn = sqlite3.connect(str(self.cache_db), check_same_thread=False)
            conn.execute("DELETE FROM cache WHERE key=?", (key,))
            conn.commit()
            conn.close()
            
            _log.debug(f"Cache DELETE: {key}")
            return True
        
        except Exception as e:
            _log.error(f"Cache DELETE error for {key}: {e}")
            return False
    
    def clear_expired(self) -> int:
        """
        Clear all expired cache entries.
        
        Returns:
            Number of entries deleted
        """
        try:
            conn = sqlite3.connect(str(self.cache_db), check_same_thread=False)
            cursor = conn.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted > 0:
                _log.info(f"Cleared {deleted} expired cache entries")
            
            return deleted
        
        except Exception as e:
            _log.error(f"Cache CLEAR_EXPIRED error: {e}")
            return 0
    
    def clear_all(self) -> bool:
        """Clear all cache entries."""
        try:
            conn = sqlite3.connect(str(self.cache_db), check_same_thread=False)
            conn.execute("DELETE FROM cache")
            conn.commit()
            conn.close()
            
            _log.info("Cleared all cache entries")
            return True
        
        except Exception as e:
            _log.error(f"Cache CLEAR_ALL error: {e}")
            return False
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        try:
            conn = sqlite3.connect(str(self.cache_db), check_same_thread=False)
            
            total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            expired = conn.execute(
                "SELECT COUNT(*) FROM cache WHERE expires_at < ?",
                (time.time(),)
            ).fetchone()[0]
            
            conn.close()
            
            return {
                "total_entries": total,
                "expired_entries": expired,
                "valid_entries": total - expired,
            }
        
        except Exception as e:
            _log.error(f"Cache STATS error: {e}")
            return {"total_entries": 0, "expired_entries": 0, "valid_entries": 0}


# Global singleton instance
_cache_manager = DashboardCacheManager()


def get(key: str, source_data: Any = None) -> Any | None:
    """Convenience function to get from cache using the global manager."""
    return _cache_manager.get(key, source_data)


def set(
    key: str,
    value: Any,
    source_data: Any = None,
    ttl_seconds: float | None = None,
) -> bool:
    """Convenience function to set cache using the global manager."""
    return _cache_manager.set(key, value, source_data, ttl_seconds)


def delete(key: str) -> bool:
    """Convenience function to delete from cache using the global manager."""
    return _cache_manager.delete(key)


def clear_expired() -> int:
    """Convenience function to clear expired entries using the global manager."""
    return _cache_manager.clear_expired()


def clear_all() -> bool:
    """Convenience function to clear all cache using the global manager."""
    return _cache_manager.clear_all()


def get_stats() -> dict[str, Any]:
    """Convenience function to get cache stats using the global manager."""
    return _cache_manager.get_stats()
