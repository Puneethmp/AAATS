"""
Volatility-Adjusted Momentum Strategy.

Adjusts position sizing and entry thresholds based on volatility.
Higher volatility = smaller positions, higher entry threshold.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.momentum", "volatility_adjusted")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "atr_14", "bb_upper", "bb_lower"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate volatility-adjusted momentum signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"volatility_adjusted: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    base_momentum_threshold = cfg.get("base_momentum_threshold", 0.02)  # 2%
    
    # Calculate volatility percentile (0-1)
    df["volatility_pct"] = df["atr_14"].rank(pct=True)
    
    # Adjust momentum threshold based on volatility
    # High volatility = higher threshold needed
    df["momentum_threshold"] = base_momentum_threshold * (1 + df["volatility_pct"])
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Strong momentum + low/medium volatility
    buy_condition = (
        (df["return_5d"] > df["momentum_threshold"]) &
        (df["volatility_pct"] < 0.7) &  # Not in high volatility regime
        (df["close"] > df["bb_lower"])  # Above lower Bollinger Band
    )
    df.loc[buy_condition, "signal"] = "BUY"
    # Confidence inversely proportional to volatility
    df.loc[buy_condition, "confidence"] = 0.8 - (0.3 * df["volatility_pct"])
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.5 * df["atr_14"])
    
    # SELL: Momentum reversal or high volatility spike
    sell_condition = (
        (df["return_5d"] < -df["momentum_threshold"]) |
        (df["volatility_pct"] > 0.9)  # Extreme volatility
    )
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
