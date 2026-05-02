"""
Watchdog and recovery system for AAATS.

Monitors trading processes and automatically restarts them on failure.
Lightweight implementation suitable for Oracle Cloud free-tier VM.
"""

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from foundation.logger import get_logger

_log = get_logger("infrastructure", "watchdog")


@dataclass
class ProcessConfig:
    """Configuration for a monitored process."""
    name: str
    command: list[str]
    working_dir: str
    max_restarts: int = 5
    restart_window_seconds: int = 3600
    health_check_interval: int = 60
    restart_delay: int = 10


@dataclass
class ProcessState:
    """Runtime state of a monitored process."""
    name: str
    pid: Optional[int] = None
    status: str = "STOPPED"  # STOPPED, RUNNING, CRASHED, DISABLED
    last_start: Optional[str] = None
    last_crash: Optional[str] = None
    restart_count: int = 0
    restart_history: list[str] = None
    
    def __post_init__(self):
        if self.restart_history is None:
            self.restart_history = []


class Watchdog:
    """
    Lightweight watchdog for monitoring and restarting trading processes.
    
    Usage:
        watchdog = Watchdog(state_file="data/watchdog_state.json")
        
        # Register processes to monitor
        watchdog.register(ProcessConfig(
            name="us_paper_trading",
            command=["python", "scripts/continuous_runner.py"],
            working_dir=".",
            max_restarts=5,
        ))
        
        # Start monitoring (blocking)
        watchdog.run()
    """
    
    def __init__(self, state_file: str = "data/watchdog_state.json"):
        """
        Initialize watchdog.
        
        Args:
            state_file: Path to JSON file for persisting process state
        """
        self.state_file = Path(state_file)
        self.processes: dict[str, ProcessConfig] = {}
        self.states: dict[str, ProcessState] = {}
        self._load_state()
    
    def register(self, config: ProcessConfig) -> None:
        """Register a process for monitoring."""
        self.processes[config.name] = config
        if config.name not in self.states:
            self.states[config.name] = ProcessState(name=config.name)
        _log.info(f"Registered process: {config.name}")
    
    def start_process(self, name: str) -> bool:
        """
        Start a monitored process.
        
        Args:
            name: Process name
        
        Returns:
            True if started successfully, False otherwise
        """
        if name not in self.processes:
            _log.error(f"Unknown process: {name}")
            return False
        
        config = self.processes[name]
        state = self.states[name]
        
        # Check if already running
        if state.status == "RUNNING" and state.pid:
            if self._is_process_alive(state.pid):
                _log.warning(f"Process {name} already running (PID {state.pid})")
                return True
        
        # Check restart limits
        if not self._can_restart(name):
            _log.error(
                f"Process {name} exceeded restart limit "
                f"({config.max_restarts} in {config.restart_window_seconds}s)"
            )
            state.status = "DISABLED"
            self._save_state()
            return False
        
        # Start process
        try:
            _log.info(f"Starting process: {name}")
            proc = subprocess.Popen(
                config.command,
                cwd=config.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            
            # Update state
            now = datetime.now(timezone.utc).isoformat()
            state.pid = proc.pid
            state.status = "RUNNING"
            state.last_start = now
            state.restart_count += 1
            state.restart_history.append(now)
            
            # Trim old restart history
            cutoff = time.time() - config.restart_window_seconds
            state.restart_history = [
                ts for ts in state.restart_history
                if datetime.fromisoformat(ts).timestamp() > cutoff
            ]
            
            self._save_state()
            _log.info(f"Process {name} started (PID {proc.pid})")
            return True
        
        except Exception as exc:
            _log.error(f"Failed to start process {name}: {exc}")
            state.status = "CRASHED"
            state.last_crash = datetime.now(timezone.utc).isoformat()
            self._save_state()
            return False
    
    def stop_process(self, name: str) -> bool:
        """
        Stop a monitored process.
        
        Args:
            name: Process name
        
        Returns:
            True if stopped successfully, False otherwise
        """
        if name not in self.states:
            _log.error(f"Unknown process: {name}")
            return False
        
        state = self.states[name]
        
        if state.status != "RUNNING" or not state.pid:
            _log.warning(f"Process {name} not running")
            return True
        
        try:
            _log.info(f"Stopping process {name} (PID {state.pid})")
            import signal
            import os
            os.kill(state.pid, signal.SIGTERM)
            
            # Wait for graceful shutdown
            for _ in range(10):
                if not self._is_process_alive(state.pid):
                    break
                time.sleep(1)
            else:
                # Force kill if still running
                _log.warning(f"Force killing process {name}")
                os.kill(state.pid, signal.SIGKILL)
            
            state.status = "STOPPED"
            state.pid = None
            self._save_state()
            _log.info(f"Process {name} stopped")
            return True
        
        except Exception as exc:
            _log.error(f"Failed to stop process {name}: {exc}")
            return False
    
    def check_health(self, name: str) -> bool:
        """
        Check if a process is healthy.
        
        Args:
            name: Process name
        
        Returns:
            True if healthy, False if crashed or unhealthy
        """
        if name not in self.states:
            return False
        
        state = self.states[name]
        
        if state.status != "RUNNING" or not state.pid:
            return False
        
        # Check if process is alive
        if not self._is_process_alive(state.pid):
            _log.warning(f"Process {name} (PID {state.pid}) is dead")
            state.status = "CRASHED"
            state.last_crash = datetime.now(timezone.utc).isoformat()
            state.pid = None
            self._save_state()
            return False
        
        return True
    
    def run(self, check_interval: int = 30) -> None:
        """
        Run watchdog monitoring loop (blocking).
        
        Args:
            check_interval: Seconds between health checks
        """
        _log.info("Watchdog started")
        
        # Start all registered processes
        for name in self.processes:
            if self.states[name].status != "DISABLED":
                self.start_process(name)
        
        try:
            while True:
                time.sleep(check_interval)
                
                for name, config in self.processes.items():
                    state = self.states[name]
                    
                    # Skip disabled processes
                    if state.status == "DISABLED":
                        continue
                    
                    # Check health
                    if not self.check_health(name):
                        _log.warning(f"Process {name} unhealthy, restarting...")
                        
                        # Wait before restart
                        time.sleep(config.restart_delay)
                        
                        # Attempt restart
                        if not self.start_process(name):
                            _log.error(f"Failed to restart process {name}")
        
        except KeyboardInterrupt:
            _log.info("Watchdog interrupted, stopping all processes...")
            for name in self.processes:
                self.stop_process(name)
    
    def _can_restart(self, name: str) -> bool:
        """Check if process can be restarted based on limits."""
        config = self.processes[name]
        state = self.states[name]
        
        # Count recent restarts
        cutoff = time.time() - config.restart_window_seconds
        recent_restarts = sum(
            1 for ts in state.restart_history
            if datetime.fromisoformat(ts).timestamp() > cutoff
        )
        
        return recent_restarts < config.max_restarts
    
    def _is_process_alive(self, pid: int) -> bool:
        """Check if process with given PID is alive."""
        try:
            import os
            import signal
            os.kill(pid, 0)
            return True
        except (OSError, AttributeError):
            return False
    
    def _load_state(self) -> None:
        """Load process state from disk."""
        if not self.state_file.exists():
            return
        
        try:
            data = json.loads(self.state_file.read_text())
            for name, state_dict in data.items():
                self.states[name] = ProcessState(**state_dict)
            _log.info(f"Loaded state for {len(self.states)} processes")
        except Exception as exc:
            _log.error(f"Failed to load state: {exc}")
    
    def _save_state(self) -> None:
        """Save process state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                name: {
                    "name": state.name,
                    "pid": state.pid,
                    "status": state.status,
                    "last_start": state.last_start,
                    "last_crash": state.last_crash,
                    "restart_count": state.restart_count,
                    "restart_history": state.restart_history,
                }
                for name, state in self.states.items()
            }
            self.state_file.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            _log.error(f"Failed to save state: {exc}")
