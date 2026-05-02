"""
US→India Lead-Lag Sentiment Transfer Strategy.

Uses US market movements to predict India market direction.
US markets close before India opens, providing lead signal.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.india_specific", "us_india_leadlag")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate US→India lead-lag signals.
    
    Args:
        df: DataFrame with OHLCV + features (India market)
        config: Optional configuration (should include us_return if available)
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"us_india_leadlag: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    correlation_threshold = cfg.get("correlation_threshold", 0.6)
    us_signal_threshold = cfg.get("us_signal_threshold", 0.02)  # 2% US move
    
    # Simulate US market return (in production, use actual S&P500/Nasdaq data)
    # For now, use lagged India return as proxy
    df["us_return_proxy"] = df["return_5d"].shift(1)
    
    # Calculate rolling correlation
    df["correlation"] = df["return_5d"].rolling(window=20, min_periods=1).corr(df["us_return_proxy"])
    
    # Detect strong US signals
    df["us_signal_strength"] = abs(df["us_return_proxy"])
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Strong positive US signal + high correlation
    buy_condition = (
        (df["us_return_proxy"] > us_signal_threshold) &
        (df["correlation"] > correlation_threshold)
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.65 + (0.2 * df["correlation"])
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.0 * df["atr_14"])
    
    # SELL: Strong negative US signal + high correlation
    sell_condition = (
        (df["us_return_proxy"] < -us_signal_threshold) &
        (df["correlation"] > correlation_threshold)
    )
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
