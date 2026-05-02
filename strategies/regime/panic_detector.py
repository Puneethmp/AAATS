"""
Panic/Crash Regime Detection Strategy.

Detects market panic and crash conditions.
Implements risk-off positioning during extreme stress.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.regime", "panic_detector")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate panic/crash regime detection signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss, regime columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"panic_detector: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    crash_threshold = cfg.get("crash_threshold", -0.07)  # -7% drop
    panic_vol_threshold = cfg.get("panic_vol_threshold", 0.95)  # 95th percentile
    
    # Calculate panic indicators
    df["atr_percentile"] = df["atr_14"].rank(pct=True)
    df["return_percentile"] = df["return_5d"].rank(pct=True)
    
    # Classify regime
    df["regime"] = "NORMAL"
    df.loc[
        (df["return_5d"] < crash_threshold) | 
        ((df["atr_percentile"] > panic_vol_threshold) & (df["return_5d"] < -0.03)),
        "regime"
    ] = "PANIC"
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # SELL: Panic detected (risk-off)
    panic_sell = df["regime"] == "PANIC"
    df.loc[panic_sell, "signal"] = "SELL"
    df.loc[panic_sell, "confidence"] = 0.95  # Very high confidence to exit
    
    # BUY: Recovery after panic (contrarian)
    recovery_buy = (
        (df["regime"] == "NORMAL") &
        (df["regime"].shift(1) == "PANIC") &
        (df["return_5d"] > 0)
    )
    df.loc[recovery_buy, "signal"] = "BUY"
    df.loc[recovery_buy, "confidence"] = 0.65
    df.loc[recovery_buy, "stop_loss"] = df["close"] - (3.0 * df["atr_14"])
    
    _log.debug(f"Panic periods detected: {panic_sell.sum()}, Recovery opportunities: {recovery_buy.sum()}")
    
    return df
