"""
Z-Score Deviation Reversion Strategy.

Trades mean reversion when price deviates significantly from moving average.
Uses z-score to identify overextended moves.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.mean_reversion", "zscore_reversion")

_REQUIRED_COLS = {"timestamp", "close", "sma_20", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate z-score reversion signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"zscore_reversion: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    zscore_buy_threshold = cfg.get("zscore_buy_threshold", -2.0)  # Oversold
    zscore_sell_threshold = cfg.get("zscore_sell_threshold", 2.0)  # Overbought
    
    # Calculate z-score
    df["std_20"] = df["close"].rolling(window=20, min_periods=1).std()
    df["zscore"] = (df["close"] - df["sma_20"]) / df["std_20"]
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Oversold (price below mean by 2+ std devs)
    buy_condition = df["zscore"] < zscore_buy_threshold
    df.loc[buy_condition, "signal"] = "BUY"
    # Confidence increases with deviation
    df.loc[buy_condition, "confidence"] = np.clip(0.6 + (0.1 * abs(df["zscore"] - zscore_buy_threshold)), 0.6, 0.9)
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.0 * df["atr_14"])
    
    # SELL: Overbought (price above mean by 2+ std devs) or return to mean
    sell_condition = (df["zscore"] > zscore_sell_threshold) | (df["zscore"] > 0)
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
