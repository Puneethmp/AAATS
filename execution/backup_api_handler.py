"""
Backup API handler for AAATS.

Provides automatic failover between primary and backup API endpoints/credentials.
If primary fails, switches to backup and sends alert.

Usage:
    from execution.backup_api_handler import BackupAPIHandler
    handler = BackupAPIHandler(market="crypto")
    exchange = handler.get_exchange()  # returns primary or backup
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from foundation.logger import get_logger

_log = get_logger("execution", "backup_api_handler")


@dataclass
class APIConfig:
    name: str
    api_key: str
    api_secret: str
    base_url: str = ""
    priority: int = 0  # 0 = primary, 1 = backup


class BackupAPIHandler:
    """
    Manages primary/backup API configurations with automatic failover.

    Args:
        market:           "crypto" or "india".
        max_failures:     Consecutive failures before switching to backup.
        cooldown_seconds: Time to wait before trying primary again.
    """

    def __init__(
        self,
        market: str,
        max_failures: int = 3,
        cooldown_seconds: int = 300,
    ) -> None:
        self._market = market
        self._max_failures = max_failures
        self._cooldown = cooldown_seconds
        self._failure_count = 0
        self._using_backup = False
        self._last_switch_time: float = 0

    def record_success(self) -> None:
        """Reset failure counter on successful API call."""
        if self._failure_count > 0:
            _log.info(f"{self._market} API: success after {self._failure_count} failures")
        self._failure_count = 0

    def record_failure(self, error: str) -> bool:
        """
        Record an API failure. Returns True if should switch to backup.
        """
        self._failure_count += 1
        _log.warning(
            f"{self._market} API failure #{self._failure_count}: {error}"
        )
        if self._failure_count >= self._max_failures and not self._using_backup:
            self._switch_to_backup()
            return True
        return False

    def _switch_to_backup(self) -> None:
        _log.critical(
            f"{self._market}: switching to BACKUP API after {self._failure_count} failures"
        )
        self._using_backup = True
        self._last_switch_time = time.time()
        self._failure_count = 0
        try:
            from observability.alerts import send_alert
            send_alert(
                f"API FAILOVER: {self._market.upper()}\nSwitched to backup API",
                market=self._market,
            )
        except Exception:
            pass

    def try_restore_primary(self) -> bool:
        """
        Attempt to restore primary API if cooldown period has passed.
        Returns True if switched back to primary.
        """
        if not self._using_backup:
            return False
        if time.time() - self._last_switch_time < self._cooldown:
            return False
        _log.info(f"{self._market}: attempting to restore primary API")
        self._using_backup = False
        self._failure_count = 0
        return True

    @property
    def is_using_backup(self) -> bool:
        return self._using_backup

    def get_binance_exchange(self, primary_key: str, primary_secret: str,
                              backup_key: str = "", backup_secret: str = "") -> Any:
        """Return a ccxt Binance exchange using primary or backup credentials."""
        try:
            import ccxt
            key = backup_key if self._using_backup and backup_key else primary_key
            secret = backup_secret if self._using_backup and backup_secret else primary_secret
            return ccxt.binance({"apiKey": key, "secret": secret, "enableRateLimit": True})
        except ImportError:
            raise RuntimeError("ccxt not installed")
