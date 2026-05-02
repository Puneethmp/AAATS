"""
Volatility Regime Switching Strategy.

Adapts strategy based on volatility regime.
Low vol = momentum, High vol = mean reversion.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.volatility", "regime_switching")

_REQUIRED_COLS = {"timestamp", "close", "atr_14", "return_5d", "rsi_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate volatility regime switching signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"regime_switching: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    low_vol_threshold = cfg.get("low_vol_threshold", 0.3)
    high_vol_threshold = cfg.get("high_vol_threshold", 0.7)
    
    # Calculate volatility percentile
    df["atr_percentile"] = df["atr_14"].rank(pct=True)
    
    # Classify regime
    df["vol_regime"] = "MEDIUM"
    df.loc[df["atr_percentile"] < low_vol_threshold, "vol_regime"] = "LOW"
    df.loc[df["atr_percentile"] > high_vol_threshold, "vol_regime"] = "HIGH"
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # LOW VOL: Momentum strategy
    low_vol_buy = (
        (df["vol_regime"] == "LOW") &
        (df["return_5d"] > 0.02)
    )
    df.loc[low_vol_buy, "signal"] = "BUY"
    df.loc[low_vol_buy, "confidence"] = 0.7
    df.loc[low_vol_buy, "stop_loss"] = df["close"] - (1.5 * df["atr_14"])
    
    # HIGH VOL: Mean reversion strategy
    high_vol_buy = (
        (df["vol_regime"] == "HIGH") &
        (df["rsi_14"] < 30)  # Oversold
    )
    df.loc[high_vol_buy, "signal"] = "BUY"
    df.loc[high_vol_buy, "confidence"] = 0.65
    df.loc[high_vol_buy, "stop_loss"] = df["close"] - (2.5 * df["atr_14"])
    
    # SELL: Regime change or signal exhaustion
    sell_condition = (
        ((df["vol_regime"] == "LOW") & (df["return_5d"] < -0.02)) |
        ((df["vol_regime"] == "HIGH") & (df["rsi_14"] > 50))
    )
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Generated {(low_vol_buy | high_vol_buy).sum()} BUY, {sell_condition.sum()} SELL signals")
    
    return df
