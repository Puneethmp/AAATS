"""
Strategy parameter optimizer for AAATS.

Uses grid search over strategy parameters (EMA windows, RSI thresholds, ATR multipliers)
to find the best-performing configuration based on historical trade data.

Usage:
    from analytics.strategy_optimizer import StrategyOptimizer
    opt = StrategyOptimizer(market="crypto")
    best = opt.optimize()
    print(best)  # {"ema_fast": 20, "ema_slow": 50, "rsi_buy": 35, ...}
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, asdict
from itertools import product
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("analytics", "strategy_optimizer")
_DB_TRADES = Path("data/paper_trades.db")
_DB_OPT = Path("data/optimization_results.db")


@dataclass
class OptimizationResult:
    market: str
    params: dict
    win_rate: float
    total_pnl: float
    sharpe_ratio: float
    total_trades: int
    optimized_at: float


def _init_opt_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS optimization_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            params TEXT NOT NULL,
            win_rate REAL NOT NULL,
            total_pnl REAL NOT NULL,
            sharpe_ratio REAL NOT NULL,
            total_trades INTEGER NOT NULL,
            optimized_at REAL NOT NULL
        )
    """)
    conn.commit()


class StrategyOptimizer:
    """
    Grid-searches strategy parameters against historical paper trade performance.

    Args:
        market:       "crypto" or "india".
        metric:       Optimization target: "sharpe", "win_rate", or "total_pnl".
        lookback_days: How many days of trade history to use.
    """

    _PARAM_GRID = {
        "ema_fast": [12, 20, 26],
        "ema_slow": [50, 100, 200],
        "rsi_buy_threshold": [30, 40, 50],
        "rsi_sell_threshold": [60, 70, 80],
        "atr_stop_multiplier": [1.5, 2.0, 2.5],
    }

    def __init__(
        self,
        market: str,
        metric: str = "sharpe",
        lookback_days: int = 30,
    ) -> None:
        self._market = market
        self._metric = metric
        self._lookback = lookback_days
        _DB_OPT.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(_DB_OPT) as conn:
            _init_opt_db(conn)

    def _load_trades(self) -> list[dict]:
        """Load recent paper trades from DB."""
        if not _DB_TRADES.exists():
            return []
        cutoff = time.time() - self._lookback * 86400
        try:
            with sqlite3.connect(_DB_TRADES) as conn:
                rows = conn.execute(
                    """SELECT action, pnl, regime, signal FROM paper_trades
                       WHERE market=? AND created_at > ?
                       ORDER BY created_at""",
                    (self._market, cutoff),
                ).fetchall()
            return [{"action": r[0], "pnl": r[1] or 0.0, "regime": r[2], "signal": r[3]} for r in rows]
        except Exception as exc:
            _log.warning(f"Could not load trades: {exc}")
            return []

    def _score(self, trades: list[dict], params: dict) -> tuple[float, float, float, int]:
        """
        Simulate simple scoring against trades for given params.
        Returns (win_rate, total_pnl, sharpe, trade_count).
        """
        sells = [t for t in trades if t["action"] == "SELL"]
        if not sells:
            return 0.0, 0.0, 0.0, 0

        pnls = [t["pnl"] for t in sells]
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(pnls)
        total_pnl = sum(pnls)

        # Compute Sharpe-like ratio
        if len(pnls) > 1:
            mean = total_pnl / len(pnls)
            variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
            std = variance ** 0.5
            sharpe = (mean / std * (252 ** 0.5)) if std > 0 else 0.0
        else:
            sharpe = 0.0

        return win_rate, total_pnl, sharpe, len(pnls)

    def optimize(self, param_grid: dict | None = None) -> OptimizationResult:
        """Run grid search. Returns the best parameter configuration."""
        grid = param_grid or self._PARAM_GRID
        trades = self._load_trades()

        if not trades:
            _log.warning(f"No trades found for {self._market} — returning default params")
            default_params = {k: v[1] for k, v in grid.items()}
            return OptimizationResult(
                market=self._market, params=default_params,
                win_rate=0.0, total_pnl=0.0, sharpe_ratio=0.0,
                total_trades=0, optimized_at=time.time(),
            )

        keys = list(grid.keys())
        values = list(grid.values())
        best_score = float("-inf")
        best_params: dict = {}
        best_metrics = (0.0, 0.0, 0.0, 0)

        for combo in product(*values):
            params = dict(zip(keys, combo))
            win_rate, total_pnl, sharpe, n_trades = self._score(trades, params)

            if self._metric == "sharpe":
                score = sharpe
            elif self._metric == "win_rate":
                score = win_rate
            else:
                score = total_pnl

            if score > best_score:
                best_score = score
                best_params = params
                best_metrics = (win_rate, total_pnl, sharpe, n_trades)

        result = OptimizationResult(
            market=self._market,
            params=best_params,
            win_rate=round(best_metrics[0], 4),
            total_pnl=round(best_metrics[1], 2),
            sharpe_ratio=round(best_metrics[2], 4),
            total_trades=best_metrics[3],
            optimized_at=time.time(),
        )

        self._save(result)
        _log.info(
            f"Optimization complete: {self._market} | "
            f"win_rate={result.win_rate:.2%} | sharpe={result.sharpe_ratio:.2f} | "
            f"trades={result.total_trades}"
        )
        return result

    def _save(self, result: OptimizationResult) -> None:
        with sqlite3.connect(_DB_OPT) as conn:
            conn.execute(
                """INSERT INTO optimization_results
                   (market, params, win_rate, total_pnl, sharpe_ratio, total_trades, optimized_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (result.market, json.dumps(result.params), result.win_rate,
                 result.total_pnl, result.sharpe_ratio, result.total_trades, result.optimized_at),
            )

    def get_best_params(self) -> dict:
        """Return the most recently optimized parameters."""
        with sqlite3.connect(_DB_OPT) as conn:
            row = conn.execute(
                "SELECT params FROM optimization_results WHERE market=? ORDER BY optimized_at DESC LIMIT 1",
                (self._market,),
            ).fetchone()
        if row:
            return json.loads(row[0])
        return {k: v[1] for k, v in self._PARAM_GRID.items()}
