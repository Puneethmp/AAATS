"""
Process lock mechanism to prevent duplicate bot execution.

Ensures only one instance of a trading bot runs per market at a time.
Uses file-based locking compatible with Oracle Cloud Ubuntu VM.
"""

import os
import time
from pathlib import Path
from typing import Optional

from foundation.logger import get_logger

_log = get_logger("infrastructure", "process_lock")


class ProcessLock:
    """
    File-based process lock to prevent duplicate execution.
    
    Usage:
        lock = ProcessLock("us_paper_trading")
        if not lock.acquire():
            print("Another instance is running")
            sys.exit(1)
        try:
            # ... run trading loop ...
        finally:
            lock.release()
    
    Or use as context manager:
        with ProcessLock("us_paper_trading") as lock:
            if not lock.is_acquired():
                sys.exit(1)
            # ... run trading loop ...
    """
    
    def __init__(
        self,
        lock_name: str,
        lock_dir: Optional[Path] = None,
        stale_timeout_seconds: int = 3600,
    ):
        """
        Initialize process lock.
        
        Args:
            lock_name: Unique identifier for this lock (e.g., "us_paper_trading")
            lock_dir: Directory for lock files (default: data/locks)
            stale_timeout_seconds: Consider lock stale after this many seconds (default: 1 hour)
        """
        self.lock_name = lock_name
        self.lock_dir = lock_dir or Path(os.environ.get("AAATS_DATA", "data")) / "locks"
        self.lock_file = self.lock_dir / f"{lock_name}.lock"
        self.stale_timeout = stale_timeout_seconds
        self._acquired = False
        self._pid = os.getpid()
    
    def acquire(self, timeout: float = 0.0) -> bool:
        """
        Acquire the lock.
        
        Args:
            timeout: How long to wait for lock (0 = no wait, fail immediately)
        
        Returns:
            True if lock acquired, False otherwise
        """
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        
        start_time = time.time()
        while True:
            # Check if lock file exists
            if self.lock_file.exists():
                # Check if lock is stale
                try:
                    lock_data = self.lock_file.read_text().strip()
                    lock_pid, lock_time = lock_data.split(",")
                    lock_age = time.time() - float(lock_time)
                    
                    # Check if process is still running
                    if self._is_process_running(int(lock_pid)):
                        if lock_age < self.stale_timeout:
                            # Valid lock held by another process
                            if timeout == 0:
                                _log.warning(
                                    f"Lock '{self.lock_name}' held by PID {lock_pid} "
                                    f"(age: {lock_age:.0f}s)"
                                )
                                return False
                            
                            # Wait and retry
                            elapsed = time.time() - start_time
                            if elapsed >= timeout:
                                _log.warning(
                                    f"Timeout waiting for lock '{self.lock_name}' "
                                    f"(held by PID {lock_pid})"
                                )
                                return False
                            
                            time.sleep(0.5)
                            continue
                    
                    # Lock is stale or process is dead - remove it
                    _log.warning(
                        f"Removing stale lock '{self.lock_name}' "
                        f"(PID {lock_pid}, age: {lock_age:.0f}s)"
                    )
                    self.lock_file.unlink(missing_ok=True)
                
                except (ValueError, FileNotFoundError):
                    # Corrupted or missing lock file - remove it
                    _log.warning(f"Removing corrupted lock file: {self.lock_file}")
                    self.lock_file.unlink(missing_ok=True)
            
            # Try to create lock file
            try:
                lock_data = f"{self._pid},{time.time()}"
                self.lock_file.write_text(lock_data)
                self._acquired = True
                _log.info(f"Lock '{self.lock_name}' acquired by PID {self._pid}")
                return True
            
            except Exception as exc:
                _log.error(f"Failed to create lock file: {exc}")
                return False
    
    def release(self) -> None:
        """Release the lock."""
        if not self._acquired:
            return
        
        try:
            # Verify we still own the lock
            if self.lock_file.exists():
                lock_data = self.lock_file.read_text().strip()
                lock_pid = int(lock_data.split(",")[0])
                
                if lock_pid == self._pid:
                    self.lock_file.unlink()
                    _log.info(f"Lock '{self.lock_name}' released by PID {self._pid}")
                else:
                    _log.warning(
                        f"Lock '{self.lock_name}' owned by different PID {lock_pid}, "
                        f"not releasing"
                    )
        
        except Exception as exc:
            _log.error(f"Error releasing lock: {exc}")
        
        finally:
            self._acquired = False
    
    def is_acquired(self) -> bool:
        """Check if this instance holds the lock."""
        return self._acquired
    
    def _is_process_running(self, pid: int) -> bool:
        """Check if a process with given PID is running."""
        try:
            # Send signal 0 to check if process exists (Unix/Linux)
            os.kill(pid, 0)
            return True
        except (OSError, AttributeError):
            # Process doesn't exist or Windows (no os.kill)
            # On Windows, assume process is running if lock is recent
            return True
    
    def __enter__(self):
        """Context manager entry."""
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False
