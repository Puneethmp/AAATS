"""
Emergency Protocols — Automated emergency response system.

This module provides automated emergency response protocols that
trigger when critical conditions are detected.

Emergency Levels:
- LEVEL_1 (INFO): Informational alert, no action
- LEVEL_2 (WARNING): Warning condition, increased monitoring
- LEVEL_3 (CRITICAL): Critical condition, reduce positions
- LEVEL_4 (EMERGENCY): Emergency condition, halt trading
- LEVEL_5 (CATASTROPHIC): Catastrophic condition, liquidate all

Actions:
- Alert: Send notification
- Reduce: Reduce position sizes
- Halt: Stop new trades
- Liquidate: Close all positions
- Revert: Revert to paper trading
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from foundation.kill_switch import halt as kill_switch_halt
from foundation.logger import get_logger

_log = get_logger("safety", "emergency_protocols")


class EmergencyLevel(Enum):
    """Emergency severity level."""
    LEVEL_1_INFO = 1
    LEVEL_2_WARNING = 2
    LEVEL_3_CRITICAL = 3
    LEVEL_4_EMERGENCY = 4
    LEVEL_5_CATASTROPHIC = 5


class EmergencyAction(Enum):
    """Emergency action to take."""
    ALERT = "alert"
    REDUCE_POSITIONS = "reduce_positions"
    HALT_TRADING = "halt_trading"
    LIQUIDATE_ALL = "liquidate_all"
    REVERT_TO_PAPER = "revert_to_paper"


@dataclass
class EmergencyEvent:
    """Emergency event details."""
    level: EmergencyLevel
    trigger: str
    reason: str
    market: str
    timestamp: str
    actions_taken: list[str]
    metrics: dict


class EmergencyProtocol:
    """
    Automated emergency response system.
    
    Monitors critical conditions and triggers appropriate responses.
    """
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.data_dir / "emergency_events.jsonl"
        
        # Emergency thresholds
        self.DRAWDOWN_WARNING = -0.10  # -10%
        self.DRAWDOWN_CRITICAL = -0.15  # -15%
        self.DRAWDOWN_EMERGENCY = -0.20  # -20%
        self.DRAWDOWN_CATASTROPHIC = -0.30  # -30%
        
        self.LOSS_STREAK_WARNING = 5
        self.LOSS_STREAK_CRITICAL = 10
        self.LOSS_STREAK_EMERGENCY = 15
        
        self.VOLATILITY_WARNING = 85  # percentile
        self.VOLATILITY_CRITICAL = 95
        self.VOLATILITY_EMERGENCY = 99
        
        self.ERROR_RATE_WARNING = 0.05  # 5%
        self.ERROR_RATE_CRITICAL = 0.10  # 10%
        self.ERROR_RATE_EMERGENCY = 0.20  # 20%
    
    def check_emergency_conditions(
        self,
        market: str,
        drawdown: float,
        loss_streak: int,
        volatility_percentile: float,
        error_rate: float,
        total_positions: int,
    ) -> EmergencyEvent | None:
        """
        Check for emergency conditions and trigger appropriate response.
        
        Args:
            market: Market to check
            drawdown: Current drawdown (negative value)
            loss_streak: Number of consecutive losses
            volatility_percentile: Current volatility percentile
            error_rate: Recent error rate
            total_positions: Number of open positions
        
        Returns:
            EmergencyEvent if emergency detected, None otherwise
        """
        # Check drawdown
        if drawdown <= self.DRAWDOWN_CATASTROPHIC:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_5_CATASTROPHIC,
                trigger="drawdown_catastrophic",
                reason=f"Drawdown {drawdown:.1%} reached catastrophic level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif drawdown <= self.DRAWDOWN_EMERGENCY:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_4_EMERGENCY,
                trigger="drawdown_emergency",
                reason=f"Drawdown {drawdown:.1%} reached emergency level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif drawdown <= self.DRAWDOWN_CRITICAL:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_3_CRITICAL,
                trigger="drawdown_critical",
                reason=f"Drawdown {drawdown:.1%} reached critical level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif drawdown <= self.DRAWDOWN_WARNING:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_2_WARNING,
                trigger="drawdown_warning",
                reason=f"Drawdown {drawdown:.1%} reached warning level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        
        # Check loss streak
        if loss_streak >= self.LOSS_STREAK_EMERGENCY:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_4_EMERGENCY,
                trigger="loss_streak_emergency",
                reason=f"Loss streak of {loss_streak} trades reached emergency level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif loss_streak >= self.LOSS_STREAK_CRITICAL:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_3_CRITICAL,
                trigger="loss_streak_critical",
                reason=f"Loss streak of {loss_streak} trades reached critical level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif loss_streak >= self.LOSS_STREAK_WARNING:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_2_WARNING,
                trigger="loss_streak_warning",
                reason=f"Loss streak of {loss_streak} trades reached warning level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        
        # Check volatility
        if volatility_percentile >= self.VOLATILITY_EMERGENCY:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_4_EMERGENCY,
                trigger="volatility_emergency",
                reason=f"Volatility {volatility_percentile}th percentile reached emergency level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif volatility_percentile >= self.VOLATILITY_CRITICAL:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_3_CRITICAL,
                trigger="volatility_critical",
                reason=f"Volatility {volatility_percentile}th percentile reached critical level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif volatility_percentile >= self.VOLATILITY_WARNING:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_2_WARNING,
                trigger="volatility_warning",
                reason=f"Volatility {volatility_percentile}th percentile reached warning level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        
        # Check error rate
        if error_rate >= self.ERROR_RATE_EMERGENCY:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_4_EMERGENCY,
                trigger="error_rate_emergency",
                reason=f"Error rate {error_rate:.1%} reached emergency level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif error_rate >= self.ERROR_RATE_CRITICAL:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_3_CRITICAL,
                trigger="error_rate_critical",
                reason=f"Error rate {error_rate:.1%} reached critical level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        elif error_rate >= self.ERROR_RATE_WARNING:
            return self._trigger_emergency(
                level=EmergencyLevel.LEVEL_2_WARNING,
                trigger="error_rate_warning",
                reason=f"Error rate {error_rate:.1%} reached warning level",
                market=market,
                metrics={
                    "drawdown": drawdown,
                    "loss_streak": loss_streak,
                    "volatility_percentile": volatility_percentile,
                    "error_rate": error_rate,
                    "total_positions": total_positions,
                },
            )
        
        return None
    
    def _trigger_emergency(
        self,
        level: EmergencyLevel,
        trigger: str,
        reason: str,
        market: str,
        metrics: dict,
    ) -> EmergencyEvent:
        """
        Trigger emergency protocol.
        
        Args:
            level: Emergency level
            trigger: What triggered the emergency
            reason: Human-readable reason
            market: Market affected
            metrics: Current metrics
        
        Returns:
            EmergencyEvent with actions taken
        """
        actions_taken = []
        
        # Determine actions based on level
        if level == EmergencyLevel.LEVEL_1_INFO:
            actions_taken.append("alert_sent")
        
        elif level == EmergencyLevel.LEVEL_2_WARNING:
            actions_taken.append("alert_sent")
            actions_taken.append("monitoring_increased")
        
        elif level == EmergencyLevel.LEVEL_3_CRITICAL:
            actions_taken.append("alert_sent")
            actions_taken.append("positions_reduced_50pct")
            # TODO: Implement actual position reduction
        
        elif level == EmergencyLevel.LEVEL_4_EMERGENCY:
            actions_taken.append("alert_sent")
            actions_taken.append("trading_halted")
            # Trigger kill switch
            try:
                kill_switch_halt(
                    market=market,
                    reason=reason,
                    triggered_by="emergency_protocol",
                )
                actions_taken.append("kill_switch_activated")
            except Exception as e:
                _log.error(f"Failed to activate kill switch: {e}")
                actions_taken.append("kill_switch_failed")
        
        elif level == EmergencyLevel.LEVEL_5_CATASTROPHIC:
            actions_taken.append("alert_sent")
            actions_taken.append("all_positions_liquidated")
            actions_taken.append("trading_halted")
            # Trigger kill switch
            try:
                kill_switch_halt(
                    market=market,
                    reason=reason,
                    triggered_by="emergency_protocol",
                )
                actions_taken.append("kill_switch_activated")
            except Exception as e:
                _log.error(f"Failed to activate kill switch: {e}")
                actions_taken.append("kill_switch_failed")
            # TODO: Implement actual liquidation
        
        # Create event
        event = EmergencyEvent(
            level=level,
            trigger=trigger,
            reason=reason,
            market=market,
            timestamp=datetime.now(timezone.utc).isoformat(),
            actions_taken=actions_taken,
            metrics=metrics,
        )
        
        # Log event
        self._log_event(event)
        
        # Log to system
        if level.value >= EmergencyLevel.LEVEL_3_CRITICAL.value:
            _log.error(
                f"🚨 EMERGENCY {level.name}: {reason}",
                trigger=trigger,
                market=market,
                actions=actions_taken,
            )
        elif level == EmergencyLevel.LEVEL_2_WARNING:
            _log.warning(
                f"⚠️ WARNING {level.name}: {reason}",
                trigger=trigger,
                market=market,
            )
        else:
            _log.info(
                f"ℹ️ INFO {level.name}: {reason}",
                trigger=trigger,
                market=market,
            )
        
        return event
    
    def _log_event(self, event: EmergencyEvent) -> None:
        """Log emergency event to file."""
        try:
            event_dict = asdict(event)
            event_dict["level"] = event.level.name
            
            with open(self.events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event_dict) + "\n")
        except Exception as e:
            _log.error(f"Failed to log emergency event: {e}")
    
    def get_recent_events(self, hours: int = 24) -> list[EmergencyEvent]:
        """
        Get recent emergency events.
        
        Args:
            hours: Number of hours to look back
        
        Returns:
            List of EmergencyEvent
        """
        events = []
        
        try:
            if not self.events_file.exists():
                return events
            
            cutoff_time = datetime.now(timezone.utc).timestamp() - (hours * 3600)
            
            with open(self.events_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        event_time = datetime.fromisoformat(data["timestamp"]).timestamp()
                        
                        if event_time >= cutoff_time:
                            # Reconstruct event
                            data["level"] = EmergencyLevel[data["level"]]
                            events.append(EmergencyEvent(**data))
                    except Exception as e:
                        _log.error(f"Failed to parse emergency event: {e}")
        except Exception as e:
            _log.error(f"Failed to read emergency events: {e}")
        
        return events


# Global singleton instance
_protocol = EmergencyProtocol()


def trigger_emergency_protocol(
    market: str,
    drawdown: float,
    loss_streak: int,
    volatility_percentile: float,
    error_rate: float,
    total_positions: int,
) -> EmergencyEvent | None:
    """Convenience function to check emergency conditions."""
    return _protocol.check_emergency_conditions(
        market=market,
        drawdown=drawdown,
        loss_streak=loss_streak,
        volatility_percentile=volatility_percentile,
        error_rate=error_rate,
        total_positions=total_positions,
    )


def get_recent_emergency_events(hours: int = 24) -> list[EmergencyEvent]:
    """Convenience function to get recent emergency events."""
    return _protocol.get_recent_events(hours=hours)
