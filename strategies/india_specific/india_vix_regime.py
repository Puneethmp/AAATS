"""
India VIX Regime Modeling Strategy.

Uses India VIX (volatility index) to classify market regimes.
High VIX = risk-off, Low VIX = risk-on.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("strategies.india_specific", "india_vix_regime")

_REQUIRED_COLS = {"timestamp", "close", "return_5d", "atr_14"}


def generate_signals(
    df: pd.DataFrame,
    config: dict | None = None,
) -> pd.DataFrame:
    """
    Generate India VIX regime signals.
    
    Args:
        df: DataFrame with OHLCV + features
        config: Optional configuration (should include india_vix if available)
    
    Returns:
        DataFrame with signal, confidence, stop_loss, vix_regime columns
    """
    # Validate columns
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"india_vix_regime: missing columns {sorted(missing)}")
    
    df = df.copy()
    
    # Default config
    cfg = config or {}
    low_vix_threshold = cfg.get("low_vix_threshold", 15)  # VIX < 15 = low vol
    high_vix_threshold = cfg.get("high_vix_threshold", 25)  # VIX > 25 = high vol
    
    # Simulate India VIX from ATR (in production, use actual India VIX data)
    df["vix_proxy"] = (df["atr_14"] / df["close"]) * 100  # Convert to percentage
    df["vix_ma"] = df["vix_proxy"].rolling(window=10, min_periods=1).mean()
    
    # Classify VIX regime
    df["vix_regime"] = "MEDIUM"
    df.loc[df["vix_ma"] < low_vix_threshold, "vix_regime"] = "LOW"
    df.loc[df["vix_ma"] > high_vix_threshold, "vix_regime"] = "HIGH"
    
    # Generate signals
    df["signal"] = "HOLD"
    df["confidence"] = 0.5
    df["stop_loss"] = np.nan
    
    # BUY: Low VIX (risk-on) + positive momentum
    buy_condition = (
        (df["vix_regime"] == "LOW") &
        (df["return_5d"] > 0)
    )
    df.loc[buy_condition, "signal"] = "BUY"
    df.loc[buy_condition, "confidence"] = 0.75
    df.loc[buy_condition, "stop_loss"] = df["close"] - (1.5 * df["atr_14"])
    
    # SELL: High VIX (risk-off) or VIX spike
    vix_spike = df["vix_ma"].pct_change(5) > 0.3  # 30% VIX increase
    sell_condition = (
        (df["vix_regime"] == "HIGH") |
        vix_spike
    )
    df.loc[sell_condition, "signal"] = "SELL"
    df.loc[sell_condition, "confidence"] = 0.8
    
    _log.debug(f"VIX regime distribution: {df['vix_regime'].value_counts().to_dict()}")
    
    return df
