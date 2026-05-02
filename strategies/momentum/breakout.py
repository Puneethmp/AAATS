"""
Breakout Momentum Strategy.

Trades breakouts above resistance with volume confirmation.
Uses Bollinger Bands and volume for validation.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.momentum", "breakout")

_REQUIRED_COLS = {"timestamp", "close", "high", "bb_upper", "bb_lower", "volume", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate breakout momentum signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"breakout: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    volume_multiplier = cfg.get("volume_multiplier", 1.5)
    
    # Calculate volume moving average
    df["volume_ma"] = df["volume"].rolling(window=20, min_periods=1).mean()
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Breakout above upper Bollinger Band with volume
    buy_condition = (
        (df["close"] > df["bb_upper"]) &
        (df["volume"] > volume_multiplier * df["volume_ma"])
    )
    df.loc[buy_condition, "signal"] = "BUY"
    # Confidence based on volume strength
    volume_ratio = df["volume"] / df["volume_ma"]
    df.loc[buy_condition, "confidence"] = np.clip(0.6 + (0.1 * (volume_ratio - 1)), 0.6, 0.9)
    df.loc[buy_condition, "stop_loss"] = df["bb_lower"]  # Use lower band as stop
    
    # SELL: Breakdown below lower Bollinger Band
    sell_condition = df["close"] < df["bb_lower"]
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
