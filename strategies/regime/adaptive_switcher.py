"""
Adaptive Strategy Switching.

Dynamically switches between momentum and mean reversion
based on detected market regime.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.regime", "adaptive_switcher")

_REQUIRED_COLS = {"timestamp", "close", "ema_50", "ema_200", "rsi_14", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate adaptive strategy switching signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss, strategy columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"adaptive_switcher: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    trend_threshold = cfg.get("trend_threshold", 0.02)
    
    # Detect regime
    df["is_trending"] = (
        (abs(df["ema_50"] - df["ema_200"]) / df["close"] > 0.03) &
        (abs(df["return_5d"]) > trend_threshold)
    )
    
    # Select strategy
    df["active_strategy"] = "MEAN_REVERSION"
    df.loc[df["is_trending"], "active_strategy"] = "MOMENTUM"
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # MOMENTUM signals (trending regime)
    momentum_buy = (
        (df["active_strategy"] == "MOMENTUM") &
        (df["ema_50"] > df["ema_200"]) &
        (df["return_5d"] > 0)
    )
    df.loc[momentum_buy, "signal"] = "BUY"
    df.loc[momentum_buy, "confidence"] = 0.75
    df.loc[momentum_buy, "stop_loss"] = df["close"] - (2.0 * df["atr_14"])
    
    # MEAN REVERSION signals (sideways regime)
    reversion_buy = (
        (df["active_strategy"] == "MEAN_REVERSION") &
        (df["rsi_14"] < 30)
    )
    df.loc[reversion_buy, "signal"] = "BUY"
    df.loc[reversion_buy, "confidence"] = 0.7
    df.loc[reversion_buy, "stop_loss"] = df["close"] - (1.5 * df["atr_14"])
    
    # SELL signals
    momentum_sell = (
        (df["active_strategy"] == "MOMENTUM") &
        (df["ema_50"] < df["ema_200"])
    )
    reversion_sell = (
        (df["active_strategy"] == "MEAN_REVERSION") &
        (df["rsi_14"] > 50)
    )
    df.loc[momentum_sell | reversion_sell, "signal"] = "SELL"
    df.loc[momentum_sell | reversion_sell, "confidence"] = 0.7
    
    _log.debug(f"Strategy distribution: {df['active_strategy'].value_counts().to_dict()}")
    
    return df
