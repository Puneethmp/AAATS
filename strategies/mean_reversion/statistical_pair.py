"""
Statistical Pair Reversion Strategy.

Trades mean reversion based on correlation with market index.
Assumes price will revert to historical relationship with benchmark.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.mean_reversion", "statistical_pair")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate statistical pair reversion signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration (should include benchmark_returns)
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"statistical_pair: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    spread_threshold = cfg.get("spread_threshold", 2.0)  # 2 std devs
    
    # Calculate rolling correlation and beta (simplified)
    # In production, this would use actual benchmark data
    df["rolling_mean"] = df["return_5d"].rolling(window=20, min_periods=1).mean()
    df["rolling_std"] = df["return_5d"].rolling(window=20, min_periods=1).std()
    
    # Calculate spread (deviation from expected return)
    df["spread"] = (df["return_5d"] - df["rolling_mean"]) / df["rolling_std"]
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Negative spread (underperforming, expect reversion)
    buy_condition = df["spread"] < -spread_threshold
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = np.clip(0.6 + (0.1 * abs(df["spread"])), 0.6, 0.85)
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.0 * df["atr_14"])
    
    # SELL: Spread normalized or positive
    sell_condition = df["spread"] > 0
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
