"""
Crypto Grid Trading Strategy.

Places buy orders at evenly-spaced price levels below the current price (grid).
Takes profit at a fixed percentage above each buy level.
No trend direction required — profits from price oscillation within a range.

Grid construction:
  - n_levels buy orders placed at grid_spacing_pct intervals below current price
  - Each level: buy at price, take profit at price * (1 + profit_pct)
  - Stop-loss: if price drops below bottom_grid_price * (1 - stop_loss_pct)

Signal semantics (bar-level):
  BUY_LEVEL_N — price has hit the Nth grid buy level (execution places order)
  TAKE_PROFIT  — price has hit a take-profit level for an open grid order
  STOP_LOSS    — price has breached total grid stop-loss
  HOLD         — no grid event on this bar
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from foundation.logger import get_logger

_log = get_logger("crypto", "grid_trading")


@dataclass
class GridConfig:
    n_levels: int = 5                  # number of grid buy levels
    grid_spacing_pct: float = 0.02     # 2% between each grid level
    profit_pct: float = 0.015          # 1.5% take-profit per level
    stop_loss_pct: float = 0.10        # 10% below bottom grid level
    capital_per_level: float = 0.10    # 10% of total capital per grid level


@dataclass
class GridState:
    """Holds grid levels for a single symbol."""
    reference_price: float
    buy_levels: list[float] = field(default_factory=list)
    take_profit_levels: list[float] = field(default_factory=list)
    stop_loss_price: float = 0.0


def build_grid(reference_price: float, config: GridConfig | None = None) -> GridState:
    """
    Construct grid buy levels and take-profit levels from a reference price.

    Args:
        reference_price: Price around which the grid is centred (e.g. current price).
        config:          GridConfig with spacing and profit parameters.

    Returns:
        GridState with populated buy_levels, take_profit_levels, and stop_loss_price.
    """
    if config is None:
        config = GridConfig()

    if reference_price <= 0:
        raise ValueError(f"reference_price must be positive, got {reference_price}")

    buy_levels = [
        reference_price * (1 - (i + 1) * config.grid_spacing_pct)
        for i in range(config.n_levels)
    ]
    take_profit_levels = [p * (1 + config.profit_pct) for p in buy_levels]
    stop_loss_price = buy_levels[-1] * (1 - config.stop_loss_pct)

    state = GridState(
        reference_price=reference_price,
        buy_levels=buy_levels,
        take_profit_levels=take_profit_levels,
        stop_loss_price=stop_loss_price,
    )
    _log.info(
        f"Grid built — ref={reference_price:.4f}, "
        f"levels={[f'{p:.4f}' for p in buy_levels]}, "
        f"stop={stop_loss_price:.4f}"
    )
    return state


def generate_signals(
    df: pd.DataFrame,
    grid: GridState,
    config: GridConfig | None = None,
) -> pd.DataFrame:
    """
    Generate grid trading signals by scanning bar lows and highs against grid levels.

    Signal logic per bar:
      - If low <= any buy_level: signal = "BUY" (grid level triggered)
      - If high >= any take_profit_level: signal = "TAKE_PROFIT"
      - If low <= stop_loss_price: signal = "STOP_LOSS"
      - STOP_LOSS takes highest priority, then TAKE_PROFIT, then BUY.

    Args:
        df:   DataFrame with at minimum [timestamp, open, high, low, close].
        grid: GridState from build_grid().

    Returns:
        Copy of df with columns:
          signal          — "BUY" | "TAKE_PROFIT" | "STOP_LOSS" | "HOLD"
          grid_level_hit  — index of the lowest buy level hit (0-based), or -1
          grid_tp_hit     — index of the highest TP level hit (0-based), or -1
    """
    _required = {"timestamp", "open", "high", "low", "close"}
    missing = _required - set(df.columns)
    if missing:
        raise ValueError(f"grid_trading: missing columns {sorted(missing)}")

    out = df.copy()

    buy_levels = np.array(grid.buy_levels)
    tp_levels = np.array(grid.take_profit_levels)
    stop_price = grid.stop_loss_price

    signals = []
    grid_level_hits = []
    grid_tp_hits = []

    for _, row in out.iterrows():
        low = row["low"]
        high = row["high"]

        # Stop loss (highest priority)
        if low <= stop_price:
            signals.append("STOP_LOSS")
            grid_level_hits.append(-1)
            grid_tp_hits.append(-1)
            continue

        # Take profit
        tp_hit = np.where(high >= tp_levels)[0]
        if len(tp_hit) > 0:
            signals.append("TAKE_PROFIT")
            grid_level_hits.append(-1)
            grid_tp_hits.append(int(tp_hit[-1]))  # highest TP hit
            continue

        # Buy level
        buy_hit = np.where(low <= buy_levels)[0]
        if len(buy_hit) > 0:
            signals.append("BUY")
            grid_level_hits.append(int(buy_hit[-1]))  # deepest level hit
            grid_tp_hits.append(-1)
            continue

        signals.append("HOLD")
        grid_level_hits.append(-1)
        grid_tp_hits.append(-1)

    out["signal"] = signals
    out["grid_level_hit"] = grid_level_hits
    out["grid_tp_hit"] = grid_tp_hits

    counts = pd.Series(signals).value_counts().to_dict()
    _log.info(f"Grid signals — {counts}, total={len(out)}")
    return out


def compute_position_size(
    capital: float,
    config: GridConfig | None = None,
) -> float:
    """
    Capital to deploy at each grid level.

    Args:
        capital: Total available capital (in quote currency, e.g. USDT).
        config:  GridConfig (defaults if None).

    Returns:
        USD value to deploy at each triggered grid level.
    """
    if config is None:
        config = GridConfig()
    return capital * config.capital_per_level
