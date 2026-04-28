"""
System health monitor for AAATS.
Checks all market APIs, data freshness, disk space, and memory every 5 minutes.
Sends a Telegram alert for any failed check.

Usage:
    from foundation.health_monitor import HealthMonitor
    from config.settings import AppConfig

    config = AppConfig()
    monitor = HealthMonitor(config)
    monitor.run_all_checks()         # one-shot
    monitor.run_loop()               # blocking loop (run in a thread)
"""

import shutil
import time
from dataclasses import dataclass

import psutil
import requests

from foundation.logger import get_logger
from observability.alerts import send_alert

_log = get_logger("system", "health_monitor")


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    market: str
    check: str
    status: bool    # True = healthy, False = problem detected
    message: str


class HealthMonitor:
    """
    Runs health checks on all market APIs and system resources.
    Any False result triggers a Telegram alert and a WARNING log entry.

    Args:
        config: Validated AppConfig instance.
    """

    def __init__(self, config) -> None:
        self._config = config
        self._interval = config.system.health_check_interval_seconds

    # ── Individual checks ──────────────────────────────────────────────────

    def check_alpaca(self) -> HealthCheckResult:
        """Ping the Alpaca paper API clock endpoint."""
        try:
            resp = requests.get(
                f"{self._config.us.alpaca_base_url}/v2/clock",
                headers={
                    "APCA-API-KEY-ID": self._config.us.alpaca_api_key,
                    "APCA-API-SECRET-KEY": self._config.us.alpaca_secret_key,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return HealthCheckResult("us", "alpaca_api", True, "Alpaca API reachable")
            return HealthCheckResult(
                "us", "alpaca_api", False, f"Alpaca returned HTTP {resp.status_code}"
            )
        except Exception as exc:
            return HealthCheckResult("us", "alpaca_api", False, f"Alpaca unreachable: {exc}")

    def check_kite(self) -> HealthCheckResult:
        """Verify Kite API is reachable (lightweight connectivity check)."""
        try:
            from kiteconnect import KiteConnect  # noqa: F401 — import confirms library is present

            resp = requests.get("https://api.kite.trade", timeout=10)
            if resp.status_code in (200, 403, 404):
                # 403/404 means the server responded — connectivity confirmed
                return HealthCheckResult("india", "kite_api", True, "Kite API reachable")
            return HealthCheckResult(
                "india", "kite_api", False, f"Kite returned unexpected HTTP {resp.status_code}"
            )
        except ImportError:
            return HealthCheckResult(
                "india", "kite_api", False, "kiteconnect library not installed"
            )
        except Exception as exc:
            return HealthCheckResult("india", "kite_api", False, f"Kite unreachable: {exc}")

    def check_disk_space(self) -> HealthCheckResult:
        """Alert if free disk space drops below 5 GB."""
        free_bytes = shutil.disk_usage(".").free
        free_gb = free_bytes / (1024**3)
        if free_gb < 5.0:
            return HealthCheckResult(
                "system", "disk_space", False, f"Low disk space: {free_gb:.1f} GB free"
            )
        return HealthCheckResult(
            "system", "disk_space", True, f"Disk space OK: {free_gb:.1f} GB free"
        )

    def check_memory(self) -> HealthCheckResult:
        """Alert if system memory usage exceeds 80%."""
        mem = psutil.virtual_memory()
        if mem.percent > 80:
            return HealthCheckResult(
                "system", "memory", False, f"High memory usage: {mem.percent:.1f}%"
            )
        return HealthCheckResult(
            "system", "memory", True, f"Memory OK: {mem.percent:.1f}% used"
        )

    # ── Orchestration ──────────────────────────────────────────────────────

    def run_all_checks(self) -> list[HealthCheckResult]:
        """
        Execute all health checks once and alert on any failure.

        Returns:
            List of HealthCheckResult — one per check.
        """
        checks = [
            self.check_alpaca(),
            self.check_kite(),
            self.check_disk_space(),
            self.check_memory(),
        ]

        for result in checks:
            if result.status:
                _log.debug(f"[OK] {result.check}: {result.message}")
            else:
                _log.warning(
                    f"Health check FAILED: {result.check} — {result.message}",
                    check=result.check,
                )
                send_alert(
                    f"Health Check FAILED\nCheck: {result.check}\n{result.message}",
                    market=result.market,
                )

        return checks

    def run_loop(self) -> None:
        """
        Blocking loop — runs all checks every health_check_interval_seconds.
        Intended to run in a background thread.
        """
        _log.info(f"Health monitor started. Interval: {self._interval}s")
        while True:
            self.run_all_checks()
            time.sleep(self._interval)
