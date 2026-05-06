"""
Volatility Contraction Detection Strategy.

Detects low volatility periods that precede large moves.
Positions for breakout after contraction.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.volatility", "contraction_detection")

_REQUIRED_COLS = {"timestamp", "close", "atr_14", "bb_upper", "bb_lower"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate volatility contraction signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"contraction_detection: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    contraction_threshold = cfg.get("contraction_threshold", 0.2)  # 20th percentile
    
    # Calculate Bollinger Band width
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["close"]
    df["bb_width_percentile"] = df["bb_width"].rank(pct=True)
    df["atr_percentile"] = df["atr_14"].rank(pct=True)
    
    # Detect contraction
    df["is_contracted"] = (
        (df["bb_width_percentile"] < contraction_threshold) &
        (df["atr_percentile"] < contraction_threshold)
    )
    
    # Detect breakout from contraction
    df["breakout_up"] = (
        df["is_contracted"].shift(1) &
        (df["close"] > df["bb_upper"])
    )
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Breakout from contraction
    buy_condition = df["breakout_up"]
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.75
    df.loc[buy_condition, "stop_loss"] = df["bb_lower"]
    
    # SELL: Return to contraction or breakdown
    sell_condition = df["is_contracted"] | (df["close"] < df["bb_lower"])
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
