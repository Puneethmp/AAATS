"""
Momentum strategies for AAATS v5.4.

Implements various momentum-based trading strategies:
  - EMA crossover momentum
  - Volatility-adjusted momentum
  - Relative strength momentum
  - Breakout momentum
  - Multi-timeframe momentum
"""

from strategies.momentum.ema_crossover import generate_signals as ema_crossover
from strategies.momentum.volatility_adjusted import generate_signals as volatility_adjusted
from strategies.momentum.relative_strength import generate_signals as relative_strength
from strategies.momentum.breakout import generate_signals as breakout
from strategies.momentum.multi_timeframe import generate_signals as multi_timeframe

__all__ = [
    "ema_crossover",
    "volatility_adjusted",
    "relative_strength",
    "breakout",
    "multi_timeframe",
]
