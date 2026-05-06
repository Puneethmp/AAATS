"""
India Regime Shift Strategy.

Detects the current market regime and adjusts position sizing accordingly.
Does not generate independent signals — wraps the India Momentum strategy
with regime-aware position scaling.

Regimes:
  BULL_TREND       — EMA50 > EMA200, VIX < 15, ADX > 25
  RANGE_BOUND      — EMA50 ≈ EMA200 (within ema_pct_band%), ADX < 20
  HIGH_VOLATILITY  — VIX >= 20
  BEAR_TREND       — EMA50 < EMA200, VIX < 15 (no new longs)

Position scale:
  BULL_TREND       — 1.0x (full size)
  RANGE_BOUND      — 0.5x (reduced — mean reversion context, not momentum)
  HIGH_VOLATILITY  — 0.0x (no new positions)
  BEAR_TREND       — 0.0x (no new positions)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from foundation.logger import get_logger

_log = get_logger("india", "regime_shift")

Regime = Literal["BULL_TREND", "RANGE_BOUND", "HIGH_VOLATILITY", "BEAR_TREND", "UNKNOWN"]

_REQUIRED_COLS = {"ema_50", "ema_200", "india_vix", "adx_14"}

_POSITION_SCALE: dict[str, float] = {
    "BULL_TREND": 1.0,
    "RANGE_BOUND": 0.5,
    "HIGH_VOLATILITY": 0.0,
    "BEAR_TREND": 0.0,
    "UNKNOWN": 0.25,
}


@dataclass(frozen=True)
class RegimeConfig:
    vix_high_threshold: float = 20.0    # VIX >= this → HIGH_VOLATILITY
    vix_bull_threshold: float = 15.0    # VIX < this for clean BULL/BEAR detection
    adx_trend_threshold: float = 25.0   # ADX >= this → trending (not range)
    adx_range_threshold: float = 20.0   # ADX < this → range-bound
    ema_pct_band: float = 0.01          # EMA50 within ±1% of EMA200 → range-bound


def _check_cols(df: pd.DataFrame) -> None:
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"regime_shift: missing columns {sorted(missing)}")


def _classify_row(row: pd.Series, config: RegimeConfig) -> Regime:
    vix = row["india_vix"]
    ema50 = row["ema_50"]
    ema200 = row["ema_200"]
    adx = row["adx_14"]

    if vix >= config.vix_high_threshold:
        return "HIGH_VOLATILITY"

    ema_spread_pct = abs(ema50 - ema200) / ema200 if ema200 != 0 else 0.0

    if ema_spread_pct <= config.ema_pct_band and adx < config.adx_range_threshold:
        return "RANGE_BOUND"

    if ema50 > ema200:
        return "BULL_TREND"

    if ema50 < ema200:
        return "BEAR_TREND"

    return "UNKNOWN"


def detect_regime(
    df: pd.DataFrame,
    config: RegimeConfig | None = None,
) -> pd.DataFrame:
    """
    Classify each bar into a market regime and attach position scale.

    Args:
        df:     Feature-engineered DataFrame with ema_50, ema_200, india_vix, adx_14.
        config: RegimeConfig with threshold parameters.

    Returns:
        Copy of df with columns:
          regime          — one of: BULL_TREND, RANGE_BOUND, HIGH_VOLATILITY,
                            BEAR_TREND, UNKNOWN
          position_scale  — float multiplier for position sizing (0.0 to 1.0)
    """
    _check_cols(df)
    if config is None:
        config = RegimeConfig()

    out = df.copy()
    regimes = out.apply(_classify_row, axis=1, args=(config,))
    out["regime"] = regimes
    out["position_scale"] = out["regime"].map(_POSITION_SCALE)

    regime_counts = out["regime"].value_counts().to_dict()
    _log.info(f"Regime detection complete — distribution: {regime_counts}")
    return out


def scale_position(
    base_shares: int,
    regime: Regime,
) -> int:
    """
    Scale a base position size by the regime multiplier.

    Args:
        base_shares: Position size computed by the underlying strategy.
        regime:      Current market regime.

    Returns:
        Adjusted share count (rounded down, minimum 0).
    """
    scale = _POSITION_SCALE.get(regime, _POSITION_SCALE["UNKNOWN"])
    return max(int(base_shares * scale), 0)
