"""
Funding Rate Monitoring Strategy.

Monitors perpetual futures funding rates to detect market sentiment.
High positive funding = longs paying shorts (bearish signal)
High negative funding = shorts paying longs (bullish signal)
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.crypto_specific", "funding_rate")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate funding rate monitoring signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration (should include funding_rate if available)
    
    Returns:
        DataFrame with signal, confidence, stop_loss columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"funding_rate: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    high_funding_threshold = cfg.get("high_funding_threshold", 0.01)  # 1% (8h rate)
    low_funding_threshold = cfg.get("low_funding_threshold", -0.01)  # -1%
    
    # Simulate funding rate from price momentum (in production, use actual funding rate)
    # Positive momentum → positive funding (longs dominant)
    # Negative momentum → negative funding (shorts dominant)
    df["funding_rate_proxy"] = df["return_5d"] * 0.1  # Simplified proxy
    df["funding_ma"] = df["funding_rate_proxy"].rolling(window=7, min_periods=1).mean()
    
    # Detect extreme funding
    df["funding_extreme"] = "NEUTRAL"
    df.loc[df["funding_ma"] > high_funding_threshold, "funding_extreme"] = "HIGH_POSITIVE"
    df.loc[df["funding_ma"] < low_funding_threshold, "funding_extreme"] = "HIGH_NEGATIVE"
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: High negative funding (shorts paying longs, contrarian bullish)
    buy_condition = (
        (df["funding_extreme"] == "HIGH_NEGATIVE") &
        (df["return_5d"] < 0)  # Price declining but shorts overextended
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.7
    df.loc[buy_condition, "stop_loss"] = df["close"] - (2.0 * df["atr_14"])
    
    # SELL: High positive funding (longs paying shorts, contrarian bearish)
    sell_condition = (
        (df["funding_extreme"] == "HIGH_POSITIVE") &
        (df["return_5d"] > 0)  # Price rising but longs overextended
    )
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.7
    
    _log.debug(f"Funding extremes: {df['funding_extreme'].value_counts().to_dict()}")
    
    return df
