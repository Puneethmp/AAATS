"""
Market Regime Detector.

Classifies market state into four regimes for any market (US, India, Crypto).
Regime drives downstream strategy selection and position sizing.

Regimes:
  BULL_TREND       — Strong uptrend, EMA50 > EMA200, ADX > 25, VIX low
  BEAR_TREND       — Downtrend, EMA50 < EMA200, ADX > 25
  RANGE_BOUND      — Sideways, EMAs converged, ADX < 20
  HIGH_VOLATILITY  — VIX/volatility spike overrides trend classification

Classification priority (highest to lowest):
  1. HIGH_VOLATILITY  (volatility gate first)
  2. BULL_TREND
  3. BEAR_TREND
  4. RANGE_BOUND
  5. UNKNOWN          (insufficient data or edge case)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from foundation.logger import get_logger

_log = get_logger("system", "regime_detector")

Regime = Literal["BULL_TREND", "BEAR_TREND", "RANGE_BOUND", "HIGH_VOLATILITY", "UNKNOWN"]

_REQUIRED_COLS = {"ema_50", "ema_200", "atr_14", "close"}
_OPTIONAL_COLS = {"adx_14", "vix"}  # used if present


@dataclass(frozen=True)
class RegimeDetectorConfig:
    # Volatility gate
    atr_pct_high_vol: float = 0.03       # ATR/close > 3% → HIGH_VOLATILITY
    vix_high_threshold: float = 20.0     # VIX >= this → HIGH_VOLATILITY (if vix col present)

    # Trend detection
    ema_pct_band: float = 0.01           # EMA50 within ±1% of EMA200 → range/convergence
    adx_trend_threshold: float = 25.0   # ADX >= this → trending
    adx_range_threshold: float = 20.0   # ADX < this → range-bound


def _classify_row(row: pd.Series, config: RegimeDetectorConfig) -> Regime:
    ema50 = row["ema_50"]
    ema200 = row["ema_200"]
    close = row["close"]
    atr = row["atr_14"]

    # Guard: insufficient data (NaN from warmup)
    if pd.isna(ema50) or pd.isna(ema200) or pd.isna(atr) or close == 0:
        return "UNKNOWN"

    # 1. Volatility gate
    atr_pct = atr / close if close > 0 else 0.0
    if atr_pct > config.atr_pct_high_vol:
        return "HIGH_VOLATILITY"

    if "vix" in row.index and not pd.isna(row["vix"]):
        if row["vix"] >= config.vix_high_threshold:
            return "HIGH_VOLATILITY"

    # 2. Trend detection via EMA spread and optional ADX
    if ema200 == 0:
        return "UNKNOWN"
    ema_spread_pct = (ema50 - ema200) / ema200

    adx = row.get("adx_14", None) if hasattr(row, "get") else (
        row["adx_14"] if "adx_14" in row.index else None
    )
    adx_is_trending = (adx is not None and not pd.isna(adx)
                       and adx >= config.adx_trend_threshold)
    adx_is_ranging = (adx is not None and not pd.isna(adx)
                      and adx < config.adx_range_threshold)

    # Range: EMAs converged and ADX confirms no trend
    if abs(ema_spread_pct) <= config.ema_pct_band and adx_is_ranging:
        return "RANGE_BOUND"

    # Bull: EMA50 > EMA200
    if ema_spread_pct > config.ema_pct_band:
        return "BULL_TREND"

    # Bear: EMA50 < EMA200
    if ema_spread_pct < -config.ema_pct_band:
        return "BEAR_TREND"

    # EMAs within band but ADX not clearly ranging → indeterminate
    return "RANGE_BOUND"


def detect(
    df: pd.DataFrame,
    config: RegimeDetectorConfig | None = None,
) -> pd.DataFrame:
    """
    Classify each bar into a market regime.

    Works for US, India, and Crypto — uses ATR-based volatility gate when
    no VIX column is present (crypto/US), and VIX column when available (India).

    Args:
        df:     Feature-engineered DataFrame.
                Required columns: ema_50, ema_200, atr_14, close.
                Optional columns: adx_14 (improves RANGE_BOUND detection),
                                  vix (used for India VIX gate).
        config: RegimeDetectorConfig (defaults if None).

    Returns:
        Copy of df with:
          regime       — Regime string for each bar
          regime_score — float: -1.0 (bear) to +1.0 (bull), 0 (range), NaN (unknown)
    """
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"regime_detector: missing required columns {sorted(missing)}")

    if config is None:
        config = RegimeDetectorConfig()

    out = df.copy()
    out["regime"] = out.apply(_classify_row, axis=1, args=(config,))

    # Numeric score for downstream ML/filters
    score_map = {
        "BULL_TREND": 1.0,
        "BEAR_TREND": -1.0,
        "RANGE_BOUND": 0.0,
        "HIGH_VOLATILITY": float("nan"),
        "UNKNOWN": float("nan"),
    }
    out["regime_score"] = out["regime"].map(score_map)

    regime_counts = out["regime"].value_counts().to_dict()
    _log.info(f"Regime detection complete — {regime_counts}, total={len(out)}")
    return out


def get_current_regime(df: pd.DataFrame, config: RegimeDetectorConfig | None = None) -> Regime:
    """
    Return the regime for the most recent bar in df.

    Args:
        df:     Feature-engineered DataFrame (latest bar used).
        config: RegimeDetectorConfig.

    Returns:
        Regime string for the last row.
    """
    if df.empty:
        return "UNKNOWN"
    result = detect(df, config)
    return str(result["regime"].iloc[-1])
