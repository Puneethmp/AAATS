"""
Volatility Compression Reversion Strategy.

Trades breakouts after periods of low volatility (compression).
Low volatility often precedes large moves.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.mean_reversion", "volatility_compression")

_REQUIRED_COLS = {"timestamp", "close", "atr_14", "bb_upper", "bb_lower"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate volatility compression reversion signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"volatility_compression: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    compression_percentile = cfg.get("compression_percentile", 0.2)  # Bottom 20%
    
    # Calculate Bollinger Band width (volatility proxy)
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["close"]
    df["bb_width_percentile"] = df["bb_width"].rank(pct=True)
    
    # Calculate ATR percentile
    df["atr_percentile"] = df["atr_14"].rank(pct=True)
    
    # Identify compression (low volatility)
    df["is_compressed"] = (
        (df["bb_width_percentile"] < compression_percentile) &
        (df["atr_percentile"] < compression_percentile)
    )
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Compression + price near lower band (anticipate upward breakout)
    buy_condition = (
        df["is_compressed"] &
        (df["close"] < (df["bb_lower"] + 0.3 * (df["bb_upper"] - df["bb_lower"])))
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.65
    df.loc[buy_condition, "stop_loss"] = df["bb_lower"]
    
    # SELL: Volatility expansion (compression ended)
    sell_condition = df["bb_width_percentile"] > 0.5
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
