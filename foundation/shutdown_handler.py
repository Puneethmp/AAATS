"""
Graceful shutdown handler for AAATS.

Registers OS signal handlers (SIGINT, SIGTERM) to:
  1. Stop accepting new orders
  2. Log all open positions
  3. Save final state
  4. Exit cleanly

Usage:
    from foundation.shutdown_handler import GracefulShutdown
    shutdown = GracefulShutdown()
    shutdown.register()
    # ... main loop ...
    while not shutdown.is_requested():
        run_cycle()
"""

from __future__ import annotations

import signal
import sys
import threading
from typing import Callable

from foundation.logger import get_logger

_log = get_logger("system", "shutdown_handler")


class GracefulShutdown:
    """
    Registers SIGINT/SIGTERM handlers for clean process termination.
    Trading loops should check is_requested() at each cycle boundary.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._callbacks: list[Callable[[], None]] = []

    def register(self) -> None:
        """Register OS signal handlers. Call once at startup from main thread."""
        signal.signal(signal.SIGINT, self._handle)
        signal.signal(signal.SIGTERM, self._handle)
        _log.info("Graceful shutdown handler registered (SIGINT + SIGTERM)")

    def add_callback(self, fn: Callable[[], None]) -> None:
        """Register a cleanup callback invoked on shutdown."""
        self._callbacks.append(fn)

    def _handle(self, signum: int, frame) -> None:
        sig_name = signal.Signals(signum).name
        _log.warning(f"Signal {sig_name} received — initiating graceful shutdown")
        self._event.set()
        for cb in self._callbacks:
            try:
                cb()
            except Exception as exc:
                _log.error(f"Shutdown callback error: {exc}")

    def is_requested(self) -> bool:
        """Return True if shutdown has been requested."""
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until shutdown requested or timeout. Returns True if shutdown."""
        return self._event.wait(timeout)

    def request_shutdown(self, reason: str = "manual") -> None:
        """Programmatically trigger shutdown (e.g. from kill switch)."""
        _log.warning(f"Shutdown requested programmatically: {reason}")
        self._event.set()


# Module-level singleton so all modules can check the same shutdown state
_shutdown = GracefulShutdown()


def get_shutdown() -> GracefulShutdown:
    return _shutdown


def register_shutdown() -> GracefulShutdown:
    """Register signal handlers and return the singleton. Call from main()."""
    _shutdown.register()
    return _shutdown
