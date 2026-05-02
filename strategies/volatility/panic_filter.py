"""
Panic Volatility Filter Strategy.

Detects panic/crash conditions and halts trading.
Extreme volatility spikes indicate market stress.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.volatility", "panic_filter")

_REQUIRED_COLS = {"timestamp", "close", "atr_14", "return_5d"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate panic filter signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"panic_filter: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    panic_threshold = cfg.get("panic_threshold", 0.95)  # 95th percentile
    crash_return_threshold = cfg.get("crash_return_threshold", -0.05)  # -5%
    
    # Calculate volatility metrics
    df["atr_percentile"] = df["atr_14"].rank(pct=True)
    df["atr_spike"] = df["atr_14"].pct_change(5)
    
    # Detect panic conditions
    df["is_panic"] = (
        (df["atr_percentile"] > panic_threshold) &
        ((df["atr_spike"] > 0.5) | (df["return_5d"] < crash_return_threshold))
    )
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # During panic: SELL everything (risk-off)
    panic_sell = df["is_panic"]
    df.loc[panic_sell, "signal"] = "SELL"
    df.loc[panic_sell, "confidence"] = 0.9  # High confidence to exit
    
    # After panic subsides: Cautious re-entry
    panic_recovery = (
        (~df["is_panic"]) &
        df["is_panic"].shift(1) &
        (df["return_5d"] > 0)
    )
    df.loc[panic_recovery, "signal"] = "BUY"
    df.loc[panic_recovery, "confidence"] = 0.6
    df.loc[panic_recovery, "stop_loss"] = df["close"] - (3.0 * df["atr_14"])
    
    _log.debug(f"Panic detected: {panic_sell.sum()} periods, Recovery: {panic_recovery.sum()} periods")
    
    return df
