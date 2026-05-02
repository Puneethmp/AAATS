"""
Regime detection strategies for AAATS v5.4.

Implements regime classification and adaptive strategies:
  - Trend regime classification
  - Sideways regime classification
  - Panic/crash regime detection
  - Adaptive strategy switching
"""

from strategies.regime.trend_classifier import generate_signals as trend_classifier
from strategies.regime.sideways_classifier import generate_signals as sideways_classifier
from strategies.regime.panic_detector import generate_signals as panic_detector
from strategies.regime.adaptive_switcher import generate_signals as adaptive_switcher

__all__ = [
    "trend_classifier",
    "sideways_classifier",
    "panic_detector",
    "adaptive_switcher",
]
