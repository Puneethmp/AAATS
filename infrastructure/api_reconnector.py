"""
API reconnection logic with exponential backoff for AAATS.

Handles automatic reconnection to broker APIs and market data feeds
with intelligent retry logic and circuit breaker pattern.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from foundation.logger import get_logger

_log = get_logger("infrastructure", "api_reconnector")


@dataclass
class ReconnectConfig:
    """Configuration for API reconnection."""
    initial_delay: float = 1.0
    max_delay: float = 60.0
    backoff_factor: float = 2.0
    max_attempts: int = 10
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 300.0


@dataclass
class ConnectionState:
    """State tracking for API connection."""
    connected: bool = False
    last_attempt: Optional[str] = None
    last_success: Optional[str] = None
    attempt_count: int = 0
    failure_count: int = 0
    circuit_open: bool = False
    circuit_open_until: Optional[str] = None


class APIReconnector:
    """
    Manages API reconnection with exponential backoff and circuit breaker.
    
    Usage:
        def connect_alpaca():
            # ... connection logic ...
            return api_client
        
        reconnector = APIReconnector("alpaca", connect_alpaca)
        
        # Connect with automatic retry
        client = reconnector.connect()
        
        # Check if connected
        if reconnector.is_connected():
            # ... use client ...
            pass
    """
    
    def __init__(
        self,
        name: str,
        connect_func: Callable,
        config: Optional[ReconnectConfig] = None,
    ):
        """
        Initialize API reconnector.
        
        Args:
            name: Name of the API (for logging)
            connect_func: Function that returns connected client or raises exception
            config: Reconnection configuration
        """
        self.name = name
        self.connect_func = connect_func
        self.config = config or ReconnectConfig()
        self.state = ConnectionState()
        self._client = None
    
    def connect(self, force: bool = False) -> Optional[any]:
        """
        Connect to API with automatic retry and exponential backoff.
        
        Args:
            force: Force reconnection even if already connected
        
        Returns:
            Connected client object, or None if connection failed
        """
        # Check if already connected
        if self.state.connected and not force and self._client:
            return self._client
        
        # Check circuit breaker
        if self._is_circuit_open():
            _log.warning(
                f"Circuit breaker open for {self.name}, "
                f"retry after {self.state.circuit_open_until}"
            )
            return None
        
        # Attempt connection with exponential backoff
        delay = self.config.initial_delay
        
        for attempt in range(1, self.config.max_attempts + 1):
            self.state.attempt_count = attempt
            self.state.last_attempt = datetime.now(timezone.utc).isoformat()
            
            try:
                _log.info(f"Connecting to {self.name} (attempt {attempt}/{self.config.max_attempts})")
                
                # Call connection function
                self._client = self.connect_func()
                
                # Connection successful
                self.state.connected = True
                self.state.last_success = datetime.now(timezone.utc).isoformat()
                self.state.failure_count = 0
                self.state.attempt_count = 0
                
                _log.info(f"Successfully connected to {self.name}")
                return self._client
            
            except Exception as exc:
                self.state.failure_count += 1
                _log.warning(
                    f"Connection attempt {attempt} failed for {self.name}: {exc}"
                )
                
                # Check if circuit breaker should open
                if self.state.failure_count >= self.config.circuit_breaker_threshold:
                    self._open_circuit()
                    return None
                
                # Wait before retry (except on last attempt)
                if attempt < self.config.max_attempts:
                    _log.info(f"Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    delay = min(delay * self.config.backoff_factor, self.config.max_delay)
        
        # All attempts failed
        _log.error(f"Failed to connect to {self.name} after {self.config.max_attempts} attempts")
        self.state.connected = False
        return None
    
    def disconnect(self) -> None:
        """Disconnect from API."""
        if self._client:
            try:
                # Try to close client if it has a close method
                if hasattr(self._client, "close"):
                    self._client.close()
            except Exception as exc:
                _log.warning(f"Error closing {self.name} client: {exc}")
        
        self._client = None
        self.state.connected = False
        _log.info(f"Disconnected from {self.name}")
    
    def reconnect(self) -> Optional[any]:
        """Disconnect and reconnect."""
        _log.info(f"Reconnecting to {self.name}")
        self.disconnect()
        return self.connect()
    
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self.state.connected and self._client is not None
    
    def get_client(self) -> Optional[any]:
        """Get the connected client object."""
        return self._client if self.state.connected else None
    
    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker."""
        self.state.circuit_open = False
        self.state.circuit_open_until = None
        self.state.failure_count = 0
        _log.info(f"Circuit breaker reset for {self.name}")
    
    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        if not self.state.circuit_open:
            return False
        
        # Check if timeout has expired
        if self.state.circuit_open_until:
            timeout = datetime.fromisoformat(self.state.circuit_open_until)
            if datetime.now(timezone.utc) > timeout:
                # Timeout expired, close circuit
                self.reset_circuit_breaker()
                return False
        
        return True
    
    def _open_circuit(self) -> None:
        """Open the circuit breaker."""
        self.state.circuit_open = True
        timeout = datetime.now(timezone.utc).timestamp() + self.config.circuit_breaker_timeout
        self.state.circuit_open_until = datetime.fromtimestamp(
            timeout, tz=timezone.utc
        ).isoformat()
        
        _log.error(
            f"Circuit breaker opened for {self.name} "
            f"(too many failures: {self.state.failure_count}). "
            f"Will retry after {self.config.circuit_breaker_timeout}s"
        )


class MultiAPIReconnector:
    """
    Manages multiple API reconnectors.
    
    Usage:
        multi = MultiAPIReconnector()
        multi.register("alpaca", connect_alpaca_func)
        multi.register("kite", connect_kite_func)
        
        # Connect all
        multi.connect_all()
        
        # Get specific client
        alpaca = multi.get_client("alpaca")
    """
    
    def __init__(self):
        """Initialize multi-API reconnector."""
        self.reconnectors: dict[str, APIReconnector] = {}
    
    def register(
        self,
        name: str,
        connect_func: Callable,
        config: Optional[ReconnectConfig] = None,
    ) -> None:
        """Register an API for reconnection management."""
        self.reconnectors[name] = APIReconnector(name, connect_func, config)
        _log.info(f"Registered API: {name}")
    
    def connect_all(self) -> dict[str, bool]:
        """
        Connect to all registered APIs.
        
        Returns:
            Dict mapping API name to connection success status
        """
        results = {}
        for name, reconnector in self.reconnectors.items():
            client = reconnector.connect()
            results[name] = client is not None
        return results
    
    def disconnect_all(self) -> None:
        """Disconnect from all APIs."""
        for reconnector in self.reconnectors.values():
            reconnector.disconnect()
    
    def get_client(self, name: str) -> Optional[any]:
        """Get client for specific API."""
        if name in self.reconnectors:
            return self.reconnectors[name].get_client()
        return None
    
    def is_connected(self, name: str) -> bool:
        """Check if specific API is connected."""
        if name in self.reconnectors:
            return self.reconnectors[name].is_connected()
        return False
    
    def reconnect(self, name: str) -> Optional[any]:
        """Reconnect specific API."""
        if name in self.reconnectors:
            return self.reconnectors[name].reconnect()
        return None
