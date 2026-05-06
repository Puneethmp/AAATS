"""
RBI Event Risk Shunt Strategy.

Reduces position sizes around RBI (Reserve Bank of India) policy events.
Central bank decisions create high uncertainty and volatility.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from foundation.logger import get_logger

_log = get_logger("strategies.india_specific", "rbi_event_risk")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate RBI event risk signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration (should include rbi_event_dates if available)
    
    Returns:
        DataFrame with signal, confidence, stop_loss, event_risk columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"rbi_event_risk: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    event_window_days = cfg.get("event_window_days", 2)  # 2 days before/after
    rbi_event_dates = cfg.get("rbi_event_dates", [])  # List of RBI policy dates
    
    # Simulate event detection (in production, use actual RBI calendar)
    # For now, detect high volatility periods as proxy for events
    df["vol_spike"] = df["atr_14"].pct_change(5) > 0.5  # 50% volatility increase
    df["is_event_window"] = df["vol_spike"].rolling(window=event_window_days, min_periods=1).max() > 0
    
    # Classify event risk
    df["event_risk"] = "NORMAL"
    df.loc[df["is_event_window"], "event_risk"] = "HIGH"
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # During event window: Reduce exposure (SELL signal with low confidence)
    event_sell = (
        (df["event_risk"] == "HIGH") &
        (df["return_5d"] < 0)  # Already declining
    )
    df.loc[event_sell, "signal"] = "SELL"
    df.loc[event_sell, "confidence"] = 0.6  # Lower confidence = smaller position
    
    # After event: Resume normal trading
    post_event_buy = (
        (df["event_risk"] == "NORMAL") &
        (df["event_risk"].shift(1) == "HIGH") &
        (df["return_5d"] > 0)  # Positive momentum post-event
    )
    df.loc[post_event_buy, "signal"] = "BUY"
    df.loc[post_event_buy, "confidence"] = 0.65
    df.loc[post_event_buy, "stop_loss"] = df["close"] - (2.5 * df["atr_14"])
    
    _log.debug(f"Event risk periods: {df['event_risk'].value_counts().to_dict()}")
    
    return df
