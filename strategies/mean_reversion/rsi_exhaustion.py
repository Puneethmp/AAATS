"""
RSI Exhaustion Reversion Strategy.

Trades mean reversion when RSI shows extreme exhaustion.
Buys oversold, sells overbought.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.mean_reversion", "rsi_exhaustion")

_REQUIRED_COLS = {"timestamp", "close", "rsi_14", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate RSI exhaustion reversion signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"rsi_exhaustion: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    rsi_oversold = cfg.get("rsi_oversold", 30)
    rsi_overbought = cfg.get("rsi_overbought", 70)
    rsi_extreme_oversold = cfg.get("rsi_extreme_oversold", 20)
    rsi_extreme_overbought = cfg.get("rsi_extreme_overbought", 80)
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: RSI oversold (anticipate bounce)
    buy_condition = df["rsi_14"] < rsi_oversold
    df.loc[buy_condition, "signal"] = "BUY"
    # Confidence increases with extreme oversold
    df.loc[buy_condition, "confidence"] = np.clip(
        0.6 + (0.3 * (rsi_oversold - df["rsi_14"]) / rsi_oversold),
        0.6,
        0.9
    )
    df.loc[buy_condition, "stop_loss"] = df["close"] - (1.5 * df["atr_14"])
    
    # SELL: RSI overbought or returned to neutral
    sell_condition = (df["rsi_14"] > rsi_overbought) | (df["rsi_14"] > 50)
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
