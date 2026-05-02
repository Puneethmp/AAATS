"""
India-specific strategies for AAATS v5.4.

Implements India market-specific strategies:
  - US→India lead-lag sentiment transfer
  - India VIX regime modeling
  - RBI event risk shunt
"""

from strategies.india_specific.us_india_leadlag import generate_signals as us_india_leadlag
from strategies.india_specific.india_vix_regime import generate_signals as india_vix_regime
from strategies.india_specific.rbi_event_risk import generate_signals as rbi_event_risk

__all__ = [
    "us_india_leadlag",
    "india_vix_regime",
    "rbi_event_risk",
]
