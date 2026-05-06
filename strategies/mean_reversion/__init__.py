"""
Mean reversion strategies for AAATS v5.4.

Implements various mean reversion trading strategies:
  - Z-score deviation reversion
  - VWAP reversion
  - Volatility compression reversion
  - RSI exhaustion reversion
  - Statistical pair reversion
"""

from strategies.mean_reversion.zscore_reversion import generate_signals as zscore_reversion
from strategies.mean_reversion.vwap_reversion import generate_signals as vwap_reversion
from strategies.mean_reversion.volatility_compression import generate_signals as volatility_compression
from strategies.mean_reversion.rsi_exhaustion import generate_signals as rsi_exhaustion
from strategies.mean_reversion.statistical_pair import generate_signals as statistical_pair

__all__ = [
    "zscore_reversion",
    "vwap_reversion",
    "volatility_compression",
    "rsi_exhaustion",
    "statistical_pair",
]
