"""
Multi-Timeframe Momentum Strategy.

Confirms momentum across multiple timeframes.
Uses short-term (5d) and medium-term (20d) returns.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.momentum", "multi_timeframe")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate multi-timeframe momentum signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"multi_timeframe: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    short_threshold = cfg.get("short_threshold", 0.02)  # 2%
    medium_threshold = cfg.get("medium_threshold", 0.05)  # 5%
    
    # Calculate medium-term return (20 days)
    df["return_20d"] = df["close"].pct_change(20)
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Positive momentum on both timeframes
    buy_condition = (
        (df["return_5d"] > short_threshold) &
        (df["return_20d"] > medium_threshold)
    )
    df.loc[buy_condition, "signal"] = "BUY"
    # Confidence based on alignment strength
    df.loc[buy_condition, "confidence"] = 0.7 + (0.2 * np.minimum(
        df["return_5d"] / short_threshold,
        df["return_20d"] / medium_threshold
    ).clip(0, 1))
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.0 * df["atr_14"])
    
    # SELL: Negative momentum on either timeframe
    sell_condition = (
        (df["return_5d"] < -short_threshold) |
        (df["return_20d"] < -medium_threshold)
    )
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
