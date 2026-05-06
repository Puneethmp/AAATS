"""
Volatility Expansion Detection Strategy.

Detects and trades volatility expansion events.
Expansion often signals trend acceleration.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.volatility", "expansion_detection")

_REQUIRED_COLS = {"timestamp", "close", "atr_14", "return_5d"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate volatility expansion signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"expansion_detection: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    expansion_threshold = cfg.get("expansion_threshold", 0.8)  # 80th percentile
    
    # Calculate ATR change rate
    df["atr_change"] = df["atr_14"].pct_change(5)
    df["atr_percentile"] = df["atr_14"].rank(pct=True)
    
    # Detect expansion
    df["is_expanding"] = (
        (df["atr_percentile"] > expansion_threshold) &
        (df["atr_change"] > 0.2)  # 20% increase in ATR
    )
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Expansion + positive momentum
    buy_condition = (
        df["is_expanding"] &
        (df["return_5d"] > 0)
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.7
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.5 * df["atr_14"])
    
    # SELL: Expansion ends or negative momentum
    sell_condition = (~df["is_expanding"]) | (df["return_5d"] < -0.02)
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.65
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
