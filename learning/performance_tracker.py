"""
Performance Tracker for AAATS Learning System

Tracks per-trade, per-strategy, and per-market performance metrics to feed
the adaptive learning loop. Provides real-time performance analytics and
historical trend analysis.

Key Features:
- Per-trade performance recording with full context
- Strategy-level aggregated metrics (Sharpe, win rate, profit factor)
- Market-level performance comparison
- Rolling window performance calculations
- Performance degradation detection
- Trade outcome classification for drift detection
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from foundation.logger import get_logger

_log = get_logger("learning", "performance_tracker")
_DB_PATH = Path("data/performance_tracking.db")


@dataclass
class TradePerformance:
    """Individual trade performance record"""
    trade_id: str
    strategy_id: str
    market: str
    symbol: str
    entry_time: float
    exit_time: float
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    holding_period_hours: float
    regime: str
    signal_confidence: float
    win: bool
    slippage_bps: float = 0.0
    commission: float = 0.0
    tags: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyPerformance:
    """Aggregated strategy performance metrics"""
    strategy_id: str
    market: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    current_drawdown: float
    avg_holding_hours: float
    avg_confidence: float
    last_trade_time: float
    performance_trend: str  # "improving", "stable", "degrading"


@dataclass
class MarketPerformance:
    """Market-level aggregated performance"""
    market: str
    total_trades: int
    total_pnl: float
    win_rate: float
    sharpe_ratio: float
    active_strategies: int
    best_strategy: str
    worst_strategy: str


def _init_db(conn: sqlite3.Connection) -> None:
    """Initialize performance tracking database schema"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_performance (
            trade_id TEXT PRIMARY KEY,
            strategy_id TEXT NOT NULL,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            entry_time REAL NOT NULL,
            exit_time REAL NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL NOT NULL,
            quantity REAL NOT NULL,
            pnl REAL NOT NULL,
            pnl_percent REAL NOT NULL,
            holding_period_hours REAL NOT NULL,
            regime TEXT NOT NULL,
            signal_confidence REAL NOT NULL,
            win INTEGER NOT NULL,
            slippage_bps REAL DEFAULT 0.0,
            commission REAL DEFAULT 0.0,
            tags TEXT DEFAULT '{}'
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_strategy_market 
        ON trade_performance(strategy_id, market)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exit_time 
        ON trade_performance(exit_time)
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id TEXT NOT NULL,
            market TEXT NOT NULL,
            snapshot_time REAL NOT NULL,
            total_trades INTEGER NOT NULL,
            win_rate REAL NOT NULL,
            sharpe_ratio REAL NOT NULL,
            total_pnl REAL NOT NULL,
            max_drawdown REAL NOT NULL
        )
    """)
    
    conn.commit()


class PerformanceTracker:
    """
    Tracks and analyzes trading performance across strategies and markets.
    
    Provides:
    - Real-time trade recording
    - Strategy performance aggregation
    - Market-level analytics
    - Performance trend detection
    - Drift detection support
    """
    
    def __init__(self, db_path: Path = _DB_PATH):
        """Initialize performance tracker with database"""
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            _init_db(conn)
        
        _log.info(f"PerformanceTracker initialized: {self.db_path}")
    
    def record_trade(self, trade: TradePerformance) -> None:
        """
        Record a completed trade's performance.
        
        Args:
            trade: TradePerformance dataclass with all trade details
        """
        import json
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trade_performance
                (trade_id, strategy_id, market, symbol, entry_time, exit_time,
                 entry_price, exit_price, quantity, pnl, pnl_percent,
                 holding_period_hours, regime, signal_confidence, win,
                 slippage_bps, commission, tags)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                trade.trade_id, trade.strategy_id, trade.market, trade.symbol,
                trade.entry_time, trade.exit_time, trade.entry_price, trade.exit_price,
                trade.quantity, trade.pnl, trade.pnl_percent, trade.holding_period_hours,
                trade.regime, trade.signal_confidence, int(trade.win),
                trade.slippage_bps, trade.commission, json.dumps(trade.tags)
            ))
            conn.commit()
        
        _log.info(
            f"Trade recorded: {trade.strategy_id} | {trade.market} | "
            f"{'WIN' if trade.win else 'LOSS'} | PnL: {trade.pnl:.2f}"
        )
    
    def get_strategy_performance(
        self,
        strategy_id: str,
        market: str,
        lookback_days: int = 30
    ) -> Optional[StrategyPerformance]:
        """
        Calculate aggregated performance metrics for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            market: Market name (crypto, india, us)
            lookback_days: Number of days to analyze
            
        Returns:
            StrategyPerformance with aggregated metrics, or None if no trades
        """
        cutoff = time.time() - (lookback_days * 86400)
        
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT pnl, pnl_percent, win, holding_period_hours, 
                       signal_confidence, exit_time
                FROM trade_performance
                WHERE strategy_id = ? AND market = ? AND exit_time > ?
                ORDER BY exit_time
            """, (strategy_id, market, cutoff)).fetchall()
        
        if not rows:
            return None
        
        pnls = [r[0] for r in rows]
        pnl_pcts = [r[1] for r in rows]
        wins = [r[2] for r in rows]
        holding_hours = [r[3] for r in rows]
        confidences = [r[4] for r in rows]
        exit_times = [r[5] for r in rows]
        
        total_trades = len(pnls)
        winning_trades = sum(wins)
        losing_trades = total_trades - winning_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        total_pnl = sum(pnls)
        avg_win = np.mean([p for p, w in zip(pnls, wins) if w]) if winning_trades > 0 else 0.0
        avg_loss = np.mean([p for p, w in zip(pnls, wins) if not w]) if losing_trades > 0 else 0.0
        
        # Profit factor
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        
        # Sharpe ratio (annualized)
        if len(pnl_pcts) > 1:
            mean_return = np.mean(pnl_pcts)
            std_return = np.std(pnl_pcts, ddof=1)
            sharpe_ratio = (mean_return / std_return * np.sqrt(252)) if std_return > 0 else 0.0
        else:
            sharpe_ratio = 0.0
        
        # Drawdown calculation
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = cumulative - running_max
        max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
        current_drawdown = float(drawdowns[-1]) if len(drawdowns) > 0 else 0.0
        
        # Performance trend (compare first half vs second half)
        if total_trades >= 10:
            mid = total_trades // 2
            first_half_sharpe = self._calculate_sharpe([pnl_pcts[i] for i in range(mid)])
            second_half_sharpe = self._calculate_sharpe([pnl_pcts[i] for i in range(mid, total_trades)])
            
            if second_half_sharpe > first_half_sharpe * 1.1:
                trend = "improving"
            elif second_half_sharpe < first_half_sharpe * 0.9:
                trend = "degrading"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"
        
        return StrategyPerformance(
            strategy_id=strategy_id,
            market=market,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_pnl=total_pnl,
            avg_win=float(avg_win),
            avg_loss=float(avg_loss),
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            avg_holding_hours=float(np.mean(holding_hours)),
            avg_confidence=float(np.mean(confidences)),
            last_trade_time=exit_times[-1],
            performance_trend=trend
        )
    
    def get_market_performance(
        self,
        market: str,
        lookback_days: int = 30
    ) -> Optional[MarketPerformance]:
        """
        Calculate market-level aggregated performance.
        
        Args:
            market: Market name
            lookback_days: Number of days to analyze
            
        Returns:
            MarketPerformance with aggregated metrics
        """
        cutoff = time.time() - (lookback_days * 86400)
        
        with sqlite3.connect(self.db_path) as conn:
            # Overall market stats
            row = conn.execute("""
                SELECT COUNT(*), SUM(pnl), AVG(CAST(win AS REAL))
                FROM trade_performance
                WHERE market = ? AND exit_time > ?
            """, (market, cutoff)).fetchone()
            
            if not row or row[0] == 0:
                return None
            
            total_trades, total_pnl, win_rate = row
            
            # Get PnL percentages for Sharpe
            pnl_pcts = conn.execute("""
                SELECT pnl_percent FROM trade_performance
                WHERE market = ? AND exit_time > ?
            """, (market, cutoff)).fetchall()
            
            pnl_pcts = [r[0] for r in pnl_pcts]
            sharpe_ratio = self._calculate_sharpe(pnl_pcts)
            
            # Strategy rankings
            strategy_pnls = conn.execute("""
                SELECT strategy_id, SUM(pnl) as total_pnl
                FROM trade_performance
                WHERE market = ? AND exit_time > ?
                GROUP BY strategy_id
                ORDER BY total_pnl DESC
            """, (market, cutoff)).fetchall()
            
            active_strategies = len(strategy_pnls)
            best_strategy = strategy_pnls[0][0] if strategy_pnls else "none"
            worst_strategy = strategy_pnls[-1][0] if strategy_pnls else "none"
        
        return MarketPerformance(
            market=market,
            total_trades=total_trades,
            total_pnl=total_pnl or 0.0,
            win_rate=win_rate or 0.0,
            sharpe_ratio=sharpe_ratio,
            active_strategies=active_strategies,
            best_strategy=best_strategy,
            worst_strategy=worst_strategy
        )
    
    def get_recent_outcomes(
        self,
        strategy_id: str,
        market: str,
        count: int = 50
    ) -> List[bool]:
        """
        Get recent trade outcomes for drift detection.
        
        Args:
            strategy_id: Strategy identifier
            market: Market name
            count: Number of recent trades to retrieve
            
        Returns:
            List of boolean outcomes (True=win, False=loss)
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT win FROM trade_performance
                WHERE strategy_id = ? AND market = ?
                ORDER BY exit_time DESC
                LIMIT ?
            """, (strategy_id, market, count)).fetchall()
        
        return [bool(r[0]) for r in rows]
    
    def snapshot_strategy(
        self,
        strategy_id: str,
        market: str,
        lookback_days: int = 30
    ) -> None:
        """
        Create a performance snapshot for historical tracking.
        
        Args:
            strategy_id: Strategy identifier
            market: Market name
            lookback_days: Lookback period for metrics
        """
        perf = self.get_strategy_performance(strategy_id, market, lookback_days)
        if not perf:
            return
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO strategy_snapshots
                (strategy_id, market, snapshot_time, total_trades, win_rate,
                 sharpe_ratio, total_pnl, max_drawdown)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                strategy_id, market, time.time(), perf.total_trades,
                perf.win_rate, perf.sharpe_ratio, perf.total_pnl, perf.max_drawdown
            ))
            conn.commit()
        
        _log.info(f"Snapshot created: {strategy_id} | {market}")
    
    def _calculate_sharpe(self, returns: List[float]) -> float:
        """Calculate annualized Sharpe ratio from returns"""
        if len(returns) < 2:
            return 0.0
        
        mean_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)
        
        if std_return == 0:
            return 0.0
        
        return float(mean_return / std_return * np.sqrt(252))
    
    def get_all_strategies(self, market: Optional[str] = None) -> List[str]:
        """
        Get list of all strategies with recorded trades.
        
        Args:
            market: Optional market filter
            
        Returns:
            List of strategy IDs
        """
        with sqlite3.connect(self.db_path) as conn:
            if market:
                rows = conn.execute("""
                    SELECT DISTINCT strategy_id FROM trade_performance
                    WHERE market = ?
                """, (market,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT DISTINCT strategy_id FROM trade_performance
                """).fetchall()
        
        return [r[0] for r in rows]
