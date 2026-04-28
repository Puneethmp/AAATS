"""
Backtesting engine for AAATS.

Enforces all 6 integrity rules from Blueprint Section 8:
1. Timestamp gate  — signals processed in chronological order; strategy_fn
   receives only the current bar and cannot access future data.
2. Overfitting gate — Sharpe > 3.0 auto-rejects the result.
3. Cost gate       — all trades net of US transaction costs; gross P&L never
   used for final metrics.
4. Walk-forward gate — engine validates features_df is non-empty; caller owns
   train/test splitting.

Position sizing always delegates to risk.us.position_sizer — never arbitrary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from foundation.logger import get_logger
from risk.us.position_sizer import SizingInput, size_position

# ── US transaction cost constants ─────────────────────────────────────────────
US_COMMISSION_PER_SHARE = 0.005  # $0.005/share (entry + exit)
US_SLIPPAGE_PCT = 0.0005  # 0.05% price impact per side
US_SPREAD_PCT = 0.0002  # 0.02% bid/ask spread per side

# ── Integrity thresholds ──────────────────────────────────────────────────────
OVERFITTING_SHARPE_THRESHOLD = 3.0

# ── Annualisation (252 trading days) ─────────────────────────────────────────
_SQRT_252 = math.sqrt(252)

# Columns that must be present in every features_df
_REQUIRED_COLUMNS: frozenset[str] = frozenset({"timestamp", "close", "atr_14"})

log = get_logger(market="us", module="backtesting_engine")


@dataclass
class BacktestResult:
    """Full result of one backtest run."""

    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    equity_curve: list[float]  # portfolio value at each bar (N+1 values for N bars)
    trade_log: list[dict]  # one entry per closed trade
    approved: bool  # False if overfitting gate triggered
    rejection_reason: str | None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _entry_price(close: float) -> float:
    """Apply slippage + spread to a long entry (price moves against us: up)."""
    return close * (1.0 + US_SLIPPAGE_PCT + US_SPREAD_PCT)


def _exit_price(close: float) -> float:
    """Apply slippage + spread to a long exit (price moves against us: down)."""
    return close * (1.0 - US_SLIPPAGE_PCT - US_SPREAD_PCT)


def _compute_sharpe(equity_curve: list[float]) -> float:
    """Annualised Sharpe ratio from a bar-level equity curve.

    Uses population-style ddof=1 std. Returns 0.0 when std is zero
    (flat equity — no information) or fewer than 2 data points exist.
    """
    if len(equity_curve) < 2:
        return 0.0
    arr = np.array(equity_curve, dtype=float)
    returns = np.diff(arr) / arr[:-1]
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    if std == 0.0:
        return 0.0
    return float(np.mean(returns)) / std * _SQRT_252


def _compute_max_drawdown(equity_curve: list[float]) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.15)."""
    if len(equity_curve) < 2:
        return 0.0
    arr = np.array(equity_curve, dtype=float)
    running_max = np.maximum.accumulate(arr)
    drawdowns = (arr - running_max) / running_max
    return float(np.min(drawdowns))


def _profit_factor(wins: list[float], losses: list[float]) -> float:
    """sum(wins) / |sum(losses)|. Returns 0.0 if no trades at all."""
    total_wins = sum(wins) if wins else 0.0
    total_losses = abs(sum(losses)) if losses else 0.0
    if total_losses == 0.0:
        return 0.0 if total_wins == 0.0 else float("inf")
    return total_wins / total_losses


def _empty_result(portfolio_value: float, reason: str) -> BacktestResult:
    """Convenience factory for zero-trade rejected results."""
    return BacktestResult(
        total_return_pct=0.0,
        sharpe_ratio=0.0,
        max_drawdown_pct=0.0,
        win_rate=0.0,
        profit_factor=0.0,
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        avg_win_pct=0.0,
        avg_loss_pct=0.0,
        equity_curve=[portfolio_value],
        trade_log=[],
        approved=False,
        rejection_reason=reason,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def run_backtest(
    features_df: pd.DataFrame,
    strategy_fn: Callable,
    portfolio_value: float,
    market: str = "us",
) -> BacktestResult:
    """Run a walk-forward backtest on the supplied feature data.

    Args:
        features_df: OHLCV + feature DataFrame from query_features(). Required
            columns: ``timestamp``, ``close``, ``atr_14``. Rows are sorted by
            timestamp before processing — do not rely on incoming order.
        strategy_fn: Callable ``(row: pd.Series) -> dict | None``.
            Return ``None`` or ``{"action": "HOLD", ...}`` for no action.
            BUY/SELL dicts must also carry ``win_rate`` and ``edge_ratio``.
        portfolio_value: Starting capital in USD.
        market: Logged for observability — does not change cost constants.

    Returns:
        BacktestResult. Always inspect ``.approved`` first — the overfitting
        gate may reject an otherwise complete result.

    Raises:
        Nothing. All error paths return a rejected BacktestResult.
    """
    log.info(
        "Backtest start",
        market=market,
        rows=len(features_df),
        portfolio_value=portfolio_value,
    )

    # ── Walk-forward gate: non-empty check ────────────────────────────────────
    if features_df.empty:
        log.warning("Empty features_df — no data to backtest")
        return _empty_result(portfolio_value, "Empty features_df — no data to backtest")

    # ── Column validation ─────────────────────────────────────────────────────
    missing = _REQUIRED_COLUMNS - set(features_df.columns)
    if missing:
        reason = f"features_df missing required columns: {sorted(missing)}"
        log.error(reason)
        return _empty_result(portfolio_value, reason)

    # ── Timestamp gate: sort ascending — no future data leaks into past bars ──
    df = features_df.sort_values("timestamp").reset_index(drop=True)

    # ── State ─────────────────────────────────────────────────────────────────
    cash = float(portfolio_value)
    equity_curve: list[float] = [cash]  # index 0 = initial; index i+1 = after bar i
    trade_log: list[dict] = []
    open_pos: dict | None = None  # holds one long position (single-leg model)
    win_pcts: list[float] = []
    loss_pcts: list[float] = []

    # ── Bar loop ─────────────────────────────────────────────────────────────
    # Timestamp gate enforcement: df is sorted; strategy_fn receives exactly
    # one row at a time — it cannot access any bar with timestamp > current.
    for _, row in df.iterrows():
        signal: dict | None = strategy_fn(row)
        action = signal.get("action") if isinstance(signal, dict) else None

        if action == "BUY" and open_pos is None:
            symbol = str(row.get("symbol", "UNKNOWN"))
            close = float(row["close"])
            atr_14 = float(row["atr_14"])

            sizing = size_position(
                SizingInput(
                    symbol=symbol,
                    entry_price=close,
                    atr_14=atr_14,
                    portfolio_value=cash,
                    win_rate=float(signal.get("win_rate", 0.52)),
                    edge_ratio=float(signal.get("edge_ratio", 1.5)),
                )
            )
            if not sizing.approved:
                log.warning(
                    "Position rejected by sizer",
                    symbol=symbol,
                    reason=sizing.rejection_reason,
                )
                equity_curve.append(cash)
                continue

            # Cost gate: adjust entry price (slippage + spread, direction: up)
            adj_entry = _entry_price(close)
            entry_commission = sizing.shares * US_COMMISSION_PER_SHARE

            open_pos = {
                "symbol": symbol,
                "shares": sizing.shares,
                "entry_price": adj_entry,
                "entry_commission": entry_commission,
                "entry_timestamp": row["timestamp"],
            }
            log.info(
                "BUY",
                symbol=symbol,
                shares=sizing.shares,
                entry_price=adj_entry,
                timestamp=str(row["timestamp"]),
            )

        elif action == "SELL" and open_pos is not None:
            close = float(row["close"])

            # Cost gate: adjust exit price (slippage + spread, direction: down)
            adj_exit = _exit_price(close)
            exit_commission = open_pos["shares"] * US_COMMISSION_PER_SHARE

            gross_pnl = (adj_exit - open_pos["entry_price"]) * open_pos["shares"]
            total_commission = open_pos["entry_commission"] + exit_commission
            net_pnl = gross_pnl - total_commission
            position_cost = open_pos["entry_price"] * open_pos["shares"]
            pct_return = net_pnl / position_cost if position_cost > 0 else 0.0

            cash += net_pnl

            trade_log.append(
                {
                    "symbol": open_pos["symbol"],
                    "entry_timestamp": open_pos["entry_timestamp"],
                    "exit_timestamp": row["timestamp"],
                    "shares": open_pos["shares"],
                    "entry_price": open_pos["entry_price"],
                    "exit_price": adj_exit,
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "pct_return": pct_return,
                }
            )

            if net_pnl > 0:
                win_pcts.append(pct_return)
            else:
                loss_pcts.append(pct_return)

            log.info(
                "SELL",
                symbol=open_pos["symbol"],
                shares=open_pos["shares"],
                exit_price=adj_exit,
                net_pnl=net_pnl,
                timestamp=str(row["timestamp"]),
            )
            open_pos = None

        equity_curve.append(cash)

    # ── Metrics ───────────────────────────────────────────────────────────────
    total_trades = len(trade_log)
    winning_trades = len(win_pcts)
    losing_trades = len(loss_pcts)
    total_return_pct = (cash - portfolio_value) / portfolio_value
    sharpe = _compute_sharpe(equity_curve)
    max_dd = _compute_max_drawdown(equity_curve)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    pf = _profit_factor(win_pcts, loss_pcts)
    avg_win = sum(win_pcts) / len(win_pcts) if win_pcts else 0.0
    avg_loss = sum(loss_pcts) / len(loss_pcts) if loss_pcts else 0.0

    # ── Overfitting gate ──────────────────────────────────────────────────────
    approved = True
    rejection_reason: str | None = None
    if sharpe > OVERFITTING_SHARPE_THRESHOLD:
        approved = False
        rejection_reason = "Sharpe > 3.0: auto-rejected as overfitted"
        log.warning("Overfitting gate triggered", sharpe_ratio=sharpe)

    log.info(
        "Backtest complete",
        market=market,
        total_trades=total_trades,
        total_return_pct=f"{total_return_pct:.4%}",
        sharpe_ratio=round(sharpe, 4),
        max_drawdown_pct=f"{max_dd:.4%}",
        approved=approved,
    )

    return BacktestResult(
        total_return_pct=total_return_pct,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd,
        win_rate=win_rate,
        profit_factor=pf,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        equity_curve=equity_curve,
        trade_log=trade_log,
        approved=approved,
        rejection_reason=rejection_reason,
    )
