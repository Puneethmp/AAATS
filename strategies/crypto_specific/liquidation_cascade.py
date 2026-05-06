"""
Liquidation Cascade Detection Strategy.

Detects potential liquidation cascades in crypto markets.
Liquidation cascades occur when leveraged positions are force-closed,
causing rapid price movements.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.crypto_specific", "liquidation_cascade")

_REQUIRED_COLS = {"timestamp", "close", "volume", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate liquidation cascade detection signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"liquidation_cascade: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    cascade_return_threshold = cfg.get("cascade_return_threshold", -0.10)  # -10% drop
    volume_spike_multiplier = cfg.get("volume_spike_multiplier", 3.0)  # 3x volume
    
    # Calculate volume metrics
    df["volume_ma"] = df["volume"].rolling(window=20, min_periods=1).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma"]
    
    # Calculate price velocity (rate of change)
    df["price_velocity"] = df["close"].pct_change(3)  # 3-period change
    
    # Detect liquidation cascade conditions
    df["is_cascade"] = (
        (df["return_5d"] < cascade_return_threshold) &  # Sharp drop
        (df["volume_ratio"] > volume_spike_multiplier) &  # Volume spike
        (df["price_velocity"] < -0.05)  # Rapid decline
    )
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # SELL: Cascade detected (exit immediately)
    cascade_sell = df["is_cascade"]
    df.loc[cascade_sell, "signal"] = "SELL"
    df.loc[cascade_sell, "confidence"] = 0.95  # Very high confidence to exit
    
    # BUY: Post-cascade recovery (contrarian entry)
    recovery_buy = (
        (~df["is_cascade"]) &
        df["is_cascade"].shift(1) &  # Was in cascade
        (df["return_5d"] > -0.05) &  # Stabilizing
        (df["volume_ratio"] < 2.0)  # Volume normalizing
    )
    df.loc[recovery_buy, "signal"] = "BUY"
    df.loc[recovery_buy, "confidence"] = 0.65
    df.loc[recovery_buy, "stop_loss"] = df["close"] - (3.0 * df["atr_14"])
    
    _log.debug(f"Cascades detected: {cascade_sell.sum()}, Recovery opportunities: {recovery_buy.sum()}")
    
    return df
