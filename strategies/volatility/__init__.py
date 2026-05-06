"""
Volatility strategies for AAATS v5.4.

Implements volatility-based trading strategies:
  - ATR breakout systems
  - Volatility expansion detection
  - Volatility contraction detection
  - Volatility regime switching
  - Panic volatility filters
"""

from strategies.volatility.atr_breakout import generate_signals as atr_breakout
from strategies.volatility.expansion_detection import generate_signals as expansion_detection
from strategies.volatility.contraction_detection import generate_signals as contraction_detection
from strategies.volatility.regime_switching import generate_signals as regime_switching
from strategies.volatility.panic_filter import generate_signals as panic_filter

__all__ = [
    "atr_breakout",
    "expansion_detection",
    "contraction_detection",
    "regime_switching",
    "panic_filter",
]
