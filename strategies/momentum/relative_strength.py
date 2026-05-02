"""
Relative Strength Momentum Strategy.

Trades assets with strong relative strength (RSI-based).
Combines RSI momentum with price momentum.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.momentum", "relative_strength")

_REQUIRED_COLS = {"timestamp", "close", "rsi_14", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate relative strength momentum signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"relative_strength: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    rsi_buy_threshold = cfg.get("rsi_buy_threshold", 55)
    rsi_sell_threshold = cfg.get("rsi_sell_threshold", 45)
    momentum_threshold = cfg.get("momentum_threshold", 0.01)  # 1%
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: RSI showing strength + positive momentum
    buy_condition = (
        (df["rsi_14"] > rsi_buy_threshold) &
        (df["rsi_14"] < 80) &  # Not overbought
        (df["return_5d"] > momentum_threshold)
    )
    df.loc[buy_condition, "signal"] = "BUY"
    # Confidence based on RSI strength
    df.loc[buy_condition, "confidence"] = 0.6 + (0.2 * (df["rsi_14"] - 50) / 30)
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.0 * df["atr_14"])
    
    # SELL: RSI showing weakness or overbought
    sell_condition = (
        (df["rsi_14"] < rsi_sell_threshold) |
        (df["rsi_14"] > 80)  # Overbought exit
    )
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
