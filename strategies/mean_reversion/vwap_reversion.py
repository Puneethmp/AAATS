"""
VWAP Reversion Strategy.

Trades mean reversion to VWAP (Volume-Weighted Average Price).
Assumes price will revert to VWAP after deviation.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.mean_reversion", "vwap_reversion")

_REQUIRED_COLS = {"timestamp", "close", "high", "low", "volume", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate VWAP reversion signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"vwap_reversion: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    deviation_threshold = cfg.get("deviation_threshold", 0.02)  # 2% deviation
    
    # Calculate VWAP
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (df["typical_price"] * df["volume"]).rolling(window=20, min_periods=1).sum() / df["volume"].rolling(window=20, min_periods=1).sum()
    
    # Calculate deviation from VWAP
    df["vwap_deviation"] = (df["close"] - df["vwap"]) / df["vwap"]
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Price significantly below VWAP
    buy_condition = df["vwap_deviation"] < -deviation_threshold
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = np.clip(0.6 + (2.0 * abs(df["vwap_deviation"])), 0.6, 0.9)
    df.loc[buy_condition, "stop_loss"] = df["close"] - (1.5 * df["atr_14"])
    
    # SELL: Price at or above VWAP (mean reversion complete)
    sell_condition = df["vwap_deviation"] >= 0
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
