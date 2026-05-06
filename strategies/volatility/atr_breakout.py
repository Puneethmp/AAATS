"""
ATR Breakout Strategy.

Trades breakouts validated by ATR expansion.
High ATR confirms genuine breakout vs false signal.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.volatility", "atr_breakout")

_REQUIRED_COLS = {"timestamp", "close", "high", "low", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate ATR breakout signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"atr_breakout: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    atr_multiplier = cfg.get("atr_multiplier", 1.5)
    lookback = cfg.get("lookback", 20)
    
    # Calculate rolling high/low
    df["rolling_high"] = df["high"].rolling(window=lookback, min_periods=1).max()
    df["rolling_low"] = df["low"].rolling(window=lookback, min_periods=1).min()
    
    # Calculate ATR percentile
    df["atr_percentile"] = df["atr_14"].rank(pct=True)
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Breakout above resistance + elevated ATR
    buy_condition = (
        (df["close"] > df["rolling_high"].shift(1)) &
        (df["atr_percentile"] > 0.6)  # ATR in upper 40%
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.65 + (0.2 * df["atr_percentile"])
    df.loc[buy_condition, "stop_loss"] = df["close"] - (atr_multiplier * df["atr_14"])
    
    # SELL: Breakdown below support
    sell_condition = df["close"] < df["rolling_low"].shift(1)
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
