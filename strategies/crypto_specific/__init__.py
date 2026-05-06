"""
Crypto-specific strategies for AAATS v5.4.

Implements cryptocurrency market-specific strategies:
  - Liquidation cascade detection
  - Funding rate monitoring
  - Crypto momentum rotation
"""

from strategies.crypto_specific.liquidation_cascade import generate_signals as liquidation_cascade
from strategies.crypto_specific.funding_rate import generate_signals as funding_rate
from strategies.crypto_specific.crypto_rotation import generate_signals as crypto_rotation

__all__ = [
    "liquidation_cascade",
    "funding_rate",
    "crypto_rotation",
]
