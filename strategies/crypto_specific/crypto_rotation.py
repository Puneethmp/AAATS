"""
Crypto Momentum Rotation Strategy.

Rotates between cryptocurrencies based on relative momentum.
Buys strongest performers, sells weakest.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.crypto_specific", "crypto_rotation")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "volume", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate crypto momentum rotation signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"crypto_rotation: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    momentum_lookback = cfg.get("momentum_lookback", 20)
    top_percentile = cfg.get("top_percentile", 0.8)  # Top 20%
    bottom_percentile = cfg.get("bottom_percentile", 0.2)  # Bottom 20%
    
    # Calculate momentum score (combination of return and volume)
    df["momentum_score"] = df["return_5d"] * np.log1p(df["volume"])
    df["momentum_rank"] = df["momentum_score"].rolling(window=momentum_lookback, min_periods=1).mean().rank(pct=True)
    
    # Calculate volatility-adjusted momentum
    df["vol_adjusted_momentum"] = df["return_5d"] / (df["atr_14"] / df["close"])
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Top momentum (strong relative strength)
    buy_condition = (
        (df["momentum_rank"] > top_percentile) &
        (df["return_5d"] > 0) &  # Positive momentum
        (df["vol_adjusted_momentum"] > 0.5)  # Strong vol-adjusted momentum
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.65 + (0.2 * (df["momentum_rank"] - top_percentile) / (1 - top_percentile))
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.0 * df["atr_14"])
    
    # SELL: Bottom momentum (weak relative strength) or momentum fading
    sell_condition = (
        (df["momentum_rank"] < bottom_percentile) |
        ((df["momentum_rank"].shift(1) > top_percentile) & (df["momentum_rank"] < 0.5))  # Momentum fading
    )
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {buy_condition.sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
