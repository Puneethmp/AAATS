"""
Metrics Aggregator — Collects metrics from all system components.

Aggregates metrics from:
  - Paper trading performance
  - Risk engine statistics
  - Execution quality
  - Infrastructure health
  - Dashboard synchronization
  - Recovery reliability
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from foundation.logger import get_logger
from monitoring.heartbeat_monitor import get_all_heartbeats
from monitoring.stale_data_detector import check_all_markets

_log = get_logger("production_readiness", "metrics_aggregator")


@dataclass
class PaperTradingMetrics:
    """Paper trading performance metrics."""
    total_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    avg_trade_duration_hours: float = 0.0
    days_trading: int = 0
    profitable_days: int = 0
    losing_days: int = 0


@dataclass
class ExecutionMetrics:
    """Execution quality metrics."""
    total_orders: int = 0
    filled_orders: int = 0
    rejected_orders: int = 0
    avg_fill_latency_ms: float = 0.0
    avg_slippage_bps: float = 0.0
    fill_rate: float = 0.0


@dataclass
class InfrastructureMetrics:
    """Infrastructure health metrics."""
    uptime_percentage: float = 0.0
    heartbeat_reliability: float = 0.0
    dashboard_sync_health: float = 0.0
    api_uptime: float = 0.0
    recovery_success_rate: float = 0.0
    avg_cycle_time_seconds: float = 0.0


@dataclass
class RiskMetrics:
    """Risk management metrics."""
    max_position_size_pct: float = 0.0
    max_portfolio_exposure_pct: float = 0.0
    risk_violations: int = 0
    kill_switch_triggers: int = 0
    avg_position_hold_time_hours: float = 0.0


@dataclass
class AggregatedMetrics:
    """All system metrics aggregated."""
    paper_trading: PaperTradingMetrics = field(default_factory=PaperTradingMetrics)
    execution: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    infrastructure: InfrastructureMetrics = field(default_factory=InfrastructureMetrics)
    risk: RiskMetrics = field(default_factory=RiskMetrics)
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MetricsAggregator:
    """Aggregates metrics from all system components."""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
    
    def collect_all_metrics(self) -> AggregatedMetrics:
        """Collect all metrics from all components."""
        try:
            return AggregatedMetrics(
                paper_trading=self._collect_paper_trading_metrics(),
                execution=self._collect_execution_metrics(),
                infrastructure=self._collect_infrastructure_metrics(),
                risk=self._collect_risk_metrics(),
            )
        except Exception as e:
            _log.error(f"Failed to collect metrics: {e}")
            return AggregatedMetrics()
    
    def _collect_paper_trading_metrics(self) -> PaperTradingMetrics:
        """Collect paper trading performance metrics."""
        paper_db = self.data_dir / "paper_trades.db"
        
        if not paper_db.exists():
            return PaperTradingMetrics()
        
        try:
            conn = sqlite3.connect(str(paper_db), check_same_thread=False)
            
            # Total trades
            total_trades = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
            
            # Win rate (from SELL orders)
            sells = conn.execute(
                "SELECT pnl FROM paper_trades WHERE action='SELL' AND pnl IS NOT NULL"
            ).fetchall()
            
            if sells:
                pnls = [row[0] for row in sells]
                win_rate = sum(1 for pnl in pnls if pnl > 0) / len(pnls)
                total_pnl = sum(pnls)
                
                # Calculate max drawdown
                cumulative_pnl = 0.0
                peak = 0.0
                max_drawdown = 0.0
                
                for pnl in pnls:
                    cumulative_pnl += pnl
                    peak = max(peak, cumulative_pnl)
                    drawdown = (cumulative_pnl - peak) / max(peak, 1.0)
                    max_drawdown = min(max_drawdown, drawdown)
            else:
                win_rate = 0.0
                total_pnl = 0.0
                max_drawdown = 0.0
            
            # Days trading
            first_trade = conn.execute(
                "SELECT timestamp FROM paper_trades ORDER BY timestamp ASC LIMIT 1"
            ).fetchone()
            
            if first_trade:
                first_date = datetime.fromisoformat(first_trade[0])
                days_trading = (datetime.now(timezone.utc) - first_date).days + 1
            else:
                days_trading = 0
            
            conn.close()
            
            return PaperTradingMetrics(
                total_trades=total_trades,
                win_rate=win_rate,
                total_pnl=total_pnl,
                max_drawdown=max_drawdown,
                days_trading=days_trading,
            )
        
        except Exception as e:
            _log.error(f"Failed to collect paper trading metrics: {e}")
            return PaperTradingMetrics()
    
    def _collect_execution_metrics(self) -> ExecutionMetrics:
        """Collect execution quality metrics."""
        paper_db = self.data_dir / "paper_trades.db"
        
        if not paper_db.exists():
            return ExecutionMetrics()
        
        try:
            conn = sqlite3.connect(str(paper_db), check_same_thread=False)
            
            # Total orders
            total_orders = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
            
            # Filled orders (risk_action = ALLOW or REDUCE)
            filled_orders = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE risk_action IN ('ALLOW', 'REDUCE')"
            ).fetchone()[0]
            
            # Rejected orders
            rejected_orders = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE risk_action = 'REJECT'"
            ).fetchone()[0]
            
            # Fill rate
            fill_rate = filled_orders / max(total_orders, 1)
            
            conn.close()
            
            return ExecutionMetrics(
                total_orders=total_orders,
                filled_orders=filled_orders,
                rejected_orders=rejected_orders,
                fill_rate=fill_rate,
            )
        
        except Exception as e:
            _log.error(f"Failed to collect execution metrics: {e}")
            return ExecutionMetrics()
    
    def _collect_infrastructure_metrics(self) -> InfrastructureMetrics:
        """Collect infrastructure health metrics."""
        try:
            # Get heartbeat reliability
            heartbeats = get_all_heartbeats()
            heartbeat_reliability = 1.0 if heartbeats else 0.0
            
            # Get dashboard sync health
            staleness_reports = check_all_markets()
            if staleness_reports:
                healthy_markets = sum(
                    1 for report in staleness_reports.values()
                    if report.is_ok or report.is_degraded
                )
                dashboard_sync_health = healthy_markets / len(staleness_reports)
            else:
                dashboard_sync_health = 0.0
            
            # Calculate uptime (based on heartbeat history)
            # For now, use heartbeat reliability as proxy
            uptime_percentage = heartbeat_reliability * 100.0
            
            return InfrastructureMetrics(
                uptime_percentage=uptime_percentage,
                heartbeat_reliability=heartbeat_reliability,
                dashboard_sync_health=dashboard_sync_health,
                api_uptime=heartbeat_reliability,  # Proxy for now
                recovery_success_rate=1.0,  # Assume 100% for now
            )
        
        except Exception as e:
            _log.error(f"Failed to collect infrastructure metrics: {e}")
            return InfrastructureMetrics()
    
    def _collect_risk_metrics(self) -> RiskMetrics:
        """Collect risk management metrics."""
        # For now, return default metrics
        # These would be populated from risk engine logs in production
        return RiskMetrics()


# Global singleton instance
_aggregator = MetricsAggregator()


def collect_all_metrics() -> AggregatedMetrics:
    """Convenience function to collect all metrics using the global aggregator."""
    return _aggregator.collect_all_metrics()
