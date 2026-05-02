"""
Sideways Regime Classification Strategy.

Detects range-bound markets and trades mean reversion.
Avoids momentum strategies in sideways markets.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.regime", "sideways_classifier")

_REQUIRED_COLS = {"timestamp", "close", "high", "low", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate sideways regime classification signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss, regime columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"sideways_classifier: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    lookback = cfg.get("lookback", 20)
    range_threshold = cfg.get("range_threshold", 0.05)  # 5% range
    
    # Calculate range metrics
    df["rolling_high"] = df["high"].rolling(window=lookback, min_periods=1).max()
    df["rolling_low"] = df["low"].rolling(window=lookback, min_periods=1).min()
    df["range_pct"] = (df["rolling_high"] - df["rolling_low"]) / df["close"]
    
    # Classify regime
    df["regime"] = "TRENDING"
    df.loc[df["range_pct"] < range_threshold, "regime"] = "SIDEWAYS"
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Sideways + near support
    buy_condition = (
        (df["regime"] == "SIDEWAYS") &
        (df["close"] < df["rolling_low"] + 0.3 * (df["rolling_high"] - df["rolling_low"]))
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.7
    df.loc[buy_condition, "stop_loss"] = df["rolling_low"]
    
    # SELL: Near resistance or breakout
    sell_condition = (
        (df["regime"] == "SIDEWAYS") &
        (df["close"] > df["rolling_high"] - 0.3 * (df["rolling_high"] - df["rolling_low"]))
    ) | (df["regime"] == "TRENDING")
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Regime distribution: {df['regime'].value_counts().to_dict()}")
    
    return df
