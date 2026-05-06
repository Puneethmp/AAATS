"""
Trend Regime Classification Strategy.

Classifies market into BULL/BEAR/NEUTRAL regimes.
Trades aligned with the dominant trend.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.regime", "trend_classifier")

_REQUIRED_COLS = {"timestamp", "close", "ema_50", "ema_200", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate trend regime classification signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration
    
    Returns:
        DataFrame with signal, confidence, stop_loss, regime columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"trend_classifier: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    trend_threshold = cfg.get("trend_threshold", 0.02)  # 2%
    
    # Classify regime
    df["regime"] = "NEUTRAL"
    df.loc[
        (df["ema_50"] > df["ema_200"]) & (df["return_5d"] > trend_threshold),
        "regime"
    ] = "BULL"
    df.loc[
        (df["ema_50"] < df["ema_200"]) & (df["return_5d"] < -trend_threshold),
        "regime"
    ] = "BEAR"
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Strong bull regime
    buy_condition = df["regime"] == "BULL"
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.75
    df.loc[buy_condition, "stop_loss"] = df["ema_50"]  # Use EMA50 as trailing stop
    
    # SELL: Bear regime or regime change
    sell_condition = (df["regime"] == "BEAR") | (df["regime"].shift(1) == "BULL") & (df["regime"] == "NEUTRAL")
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Regime distribution: {df['regime'].value_counts().to_dict()}")
    
    return df
