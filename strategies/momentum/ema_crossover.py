"""
EMA Crossover Momentum Strategy.

Entry: EMA50 > EMA200 (golden cross) + price > EMA50
Exit: EMA50 < EMA200 (death cross) OR stop loss hit
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.momentum", "ema_crossover")

_REQUIRED_COLS = {"timestamp", "close", "ema_50", "ema_200", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate EMA crossover momentum signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"ema_crossover: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    atr_stop_multiplier = cfg.get("atr_stop_multiplier", 2.0)
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Golden cross + price above EMA50
    buy_condition = (
        (df["ema_50"] > df["ema_200"]) &
        (df["close"] > df["ema_50"])
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.7
    df.loc[buy_condition, "stop_loss"] = df["close"] - (atr_stop_multiplier * df["atr_14"])
    
    # SELL: Death cross
    sell_condition = df["ema_50"] < df["ema_200"]
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
