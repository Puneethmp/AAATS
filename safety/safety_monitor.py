"""
Safety Monitor — Continuous safety monitoring and alerting.

This module provides continuous monitoring of safety metrics and
triggers alerts when thresholds are exceeded.

Monitors:
- Safety lock status
- Pre-trade validation rates
- Emergency protocol triggers
- System health metrics
- Risk exposure levels
- Strategy health scores
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Thread

from foundation.logger import get_logger
from safety.emergency_protocols import get_recent_emergency_events
from safety.live_safety_lock import check_safety_lock

_log = get_logger("safety", "safety_monitor")


@dataclass
class SafetyMetrics:
    """Current safety metrics."""
    timestamp: str
    safety_lock_status: str
    safety_lock_score: float
    recent_emergencies: int
    validation_pass_rate: float
    system_health_score: float
    total_risk_exposure: float
    average_strategy_health: float


@dataclass
class SafetyAlert:
    """Safety alert details."""
    level: str  # "info", "warning", "critical"
    message: str
    timestamp: str
    metrics: dict


class SafetyMonitor:
    """
    Continuous safety monitoring system.
    
    Runs in a background thread and monitors all safety metrics.
    """
    
    def __init__(self, check_interval_seconds: int = 60):
        self.check_interval = check_interval_seconds
        self.running = False
        self.thread = None
        
        # Alert thresholds
        self.MIN_VALIDATION_PASS_RATE = 0.90  # 90%
        self.MAX_RECENT_EMERGENCIES = 3
        self.MIN_SYSTEM_HEALTH = 80.0
        self.MAX_RISK_EXPOSURE = 0.40  # 40%
        self.MIN_STRATEGY_HEALTH = 50.0
    
    def start(self) -> None:
        """Start the safety monitor in a background thread."""
        if self.running:
            _log.warning("Safety monitor already running")
            return
        
        self.running = True
        self.thread = Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        _log.info(f"Safety monitor started (interval: {self.check_interval}s)")
    
    def stop(self) -> None:
        """Stop the safety monitor."""
        if not self.running:
            return
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        _log.info("Safety monitor stopped")
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self.running:
            try:
                # Collect metrics
                metrics = self.collect_metrics()
                
                # Check for alerts
                alerts = self.check_alerts(metrics)
                
                # Process alerts
                for alert in alerts:
                    self._process_alert(alert)
                
                # Log metrics
                _log.debug(
                    "Safety metrics collected",
                    safety_lock_status=metrics.safety_lock_status,
                    safety_lock_score=metrics.safety_lock_score,
                    recent_emergencies=metrics.recent_emergencies,
                )
            
            except Exception as e:
                _log.error(f"Error in safety monitor loop: {e}")
            
            # Sleep until next check
            time.sleep(self.check_interval)
    
    def collect_metrics(self) -> SafetyMetrics:
        """
        Collect current safety metrics.
        
        Returns:
            SafetyMetrics with current values
        """
        # Check safety lock status
        try:
            safety_lock = check_safety_lock()
            safety_lock_status = safety_lock.status.value
            safety_lock_score = safety_lock.readiness_score
        except Exception as e:
            _log.error(f"Failed to check safety lock: {e}")
            safety_lock_status = "error"
            safety_lock_score = 0.0
        
        # Count recent emergencies
        try:
            recent_events = get_recent_emergency_events(hours=24)
            recent_emergencies = len(recent_events)
        except Exception as e:
            _log.error(f"Failed to get recent emergencies: {e}")
            recent_emergencies = 0
        
        # Get validation pass rate
        # TODO: Implement actual validation rate tracking
        validation_pass_rate = 1.0  # Placeholder
        
        # Get system health score
        # TODO: Implement actual system health score
        system_health_score = 100.0  # Placeholder
        
        # Get total risk exposure
        # TODO: Implement actual risk exposure calculation
        total_risk_exposure = 0.0  # Placeholder
        
        # Get average strategy health
        # TODO: Implement actual strategy health aggregation
        average_strategy_health = 100.0  # Placeholder
        
        return SafetyMetrics(
            timestamp=datetime.now(timezone.utc).isoformat(),
            safety_lock_status=safety_lock_status,
            safety_lock_score=safety_lock_score,
            recent_emergencies=recent_emergencies,
            validation_pass_rate=validation_pass_rate,
            system_health_score=system_health_score,
            total_risk_exposure=total_risk_exposure,
            average_strategy_health=average_strategy_health,
        )
    
    def check_alerts(self, metrics: SafetyMetrics) -> list[SafetyAlert]:
        """
        Check metrics against thresholds and generate alerts.
        
        Args:
            metrics: Current safety metrics
        
        Returns:
            List of SafetyAlert
        """
        alerts = []
        
        # Check safety lock status
        if metrics.safety_lock_status == "locked":
            if metrics.safety_lock_score < 50.0:
                alerts.append(SafetyAlert(
                    level="critical",
                    message=f"Safety lock LOCKED with low score: {metrics.safety_lock_score:.1f}%",
                    timestamp=metrics.timestamp,
                    metrics={"safety_lock_score": metrics.safety_lock_score},
                ))
            else:
                alerts.append(SafetyAlert(
                    level="warning",
                    message=f"Safety lock LOCKED (score: {metrics.safety_lock_score:.1f}%)",
                    timestamp=metrics.timestamp,
                    metrics={"safety_lock_score": metrics.safety_lock_score},
                ))
        
        # Check recent emergencies
        if metrics.recent_emergencies > self.MAX_RECENT_EMERGENCIES:
            alerts.append(SafetyAlert(
                level="critical",
                message=f"Too many recent emergencies: {metrics.recent_emergencies} in last 24h",
                timestamp=metrics.timestamp,
                metrics={"recent_emergencies": metrics.recent_emergencies},
            ))
        elif metrics.recent_emergencies > 0:
            alerts.append(SafetyAlert(
                level="info",
                message=f"{metrics.recent_emergencies} emergency event(s) in last 24h",
                timestamp=metrics.timestamp,
                metrics={"recent_emergencies": metrics.recent_emergencies},
            ))
        
        # Check validation pass rate
        if metrics.validation_pass_rate < self.MIN_VALIDATION_PASS_RATE:
            alerts.append(SafetyAlert(
                level="warning",
                message=f"Low validation pass rate: {metrics.validation_pass_rate:.1%}",
                timestamp=metrics.timestamp,
                metrics={"validation_pass_rate": metrics.validation_pass_rate},
            ))
        
        # Check system health
        if metrics.system_health_score < self.MIN_SYSTEM_HEALTH:
            alerts.append(SafetyAlert(
                level="warning",
                message=f"Low system health score: {metrics.system_health_score:.1f}",
                timestamp=metrics.timestamp,
                metrics={"system_health_score": metrics.system_health_score},
            ))
        
        # Check risk exposure
        if metrics.total_risk_exposure > self.MAX_RISK_EXPOSURE:
            alerts.append(SafetyAlert(
                level="critical",
                message=f"Risk exposure {metrics.total_risk_exposure:.1%} exceeds limit {self.MAX_RISK_EXPOSURE:.1%}",
                timestamp=metrics.timestamp,
                metrics={"total_risk_exposure": metrics.total_risk_exposure},
            ))
        elif metrics.total_risk_exposure > self.MAX_RISK_EXPOSURE * 0.8:
            alerts.append(SafetyAlert(
                level="warning",
                message=f"Risk exposure {metrics.total_risk_exposure:.1%} approaching limit",
                timestamp=metrics.timestamp,
                metrics={"total_risk_exposure": metrics.total_risk_exposure},
            ))
        
        # Check strategy health
        if metrics.average_strategy_health < self.MIN_STRATEGY_HEALTH:
            alerts.append(SafetyAlert(
                level="warning",
                message=f"Low average strategy health: {metrics.average_strategy_health:.1f}",
                timestamp=metrics.timestamp,
                metrics={"average_strategy_health": metrics.average_strategy_health},
            ))
        
        return alerts
    
    def _process_alert(self, alert: SafetyAlert) -> None:
        """
        Process a safety alert.
        
        Args:
            alert: SafetyAlert to process
        """
        # Log alert
        if alert.level == "critical":
            _log.error(f"🚨 CRITICAL SAFETY ALERT: {alert.message}", **alert.metrics)
        elif alert.level == "warning":
            _log.warning(f"⚠️ SAFETY WARNING: {alert.message}", **alert.metrics)
        else:
            _log.info(f"ℹ️ SAFETY INFO: {alert.message}", **alert.metrics)
        
        # TODO: Send Telegram alert for critical alerts
        # TODO: Trigger additional actions based on alert level
    
    def get_current_status(self) -> dict:
        """
        Get current safety monitor status.
        
        Returns:
            Dict with status information
        """
        metrics = self.collect_metrics()
        alerts = self.check_alerts(metrics)
        
        return {
            "running": self.running,
            "check_interval": self.check_interval,
            "metrics": {
                "timestamp": metrics.timestamp,
                "safety_lock_status": metrics.safety_lock_status,
                "safety_lock_score": metrics.safety_lock_score,
                "recent_emergencies": metrics.recent_emergencies,
                "validation_pass_rate": metrics.validation_pass_rate,
                "system_health_score": metrics.system_health_score,
                "total_risk_exposure": metrics.total_risk_exposure,
                "average_strategy_health": metrics.average_strategy_health,
            },
            "alerts": [
                {
                    "level": alert.level,
                    "message": alert.message,
                    "timestamp": alert.timestamp,
                }
                for alert in alerts
            ],
        }


# Global singleton instance
_monitor = SafetyMonitor()


def start_safety_monitor(check_interval_seconds: int = 60) -> None:
    """Start the global safety monitor."""
    global _monitor
    _monitor = SafetyMonitor(check_interval_seconds=check_interval_seconds)
    _monitor.start()


def stop_safety_monitor() -> None:
    """Stop the global safety monitor."""
    _monitor.stop()


def get_safety_monitor_status() -> dict:
    """Get current safety monitor status."""
    return _monitor.get_current_status()
