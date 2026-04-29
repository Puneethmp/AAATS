"""
US Mean Reversion Strategy.

Entry signal:  Price deviates > N standard deviations from 20-day rolling mean
               (uses Bollinger Bands: bb_upper / bb_lower from feature engineer).
               - Oversold (short entry not supported; long reversion only):
                 close < bb_lower → BUY expecting reversion to mean.

Exit signal:   Price reverts to the 20-day mean (close >= bb_mid)
               OR stop-loss breach (close < entry - max_loss_pct * entry).

This is a long-only mean-reversion strategy. No short selling.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from foundation.logger import get_logger

_log = get_logger("us", "mean_reversion")

_REQUIRED_COLS = {"timestamp", "close", "bb_upper", "bb_mid", "bb_lower", "atr_14"}


@dataclass(frozen=True)
class MeanReversionConfig:
    max_risk_per_trade: float = 0.015   # 1.5% of capital risk per trade
    stop_loss_pct: float = 0.05         # exit if price drops 5% from entry
    atr_stop_multiplier: float = 2.5    # alternative ATR-based stop


def _check_cols(df: pd.DataFrame) -> None:
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"mean_reversion strategy: missing columns {sorted(missing)}")


def generate_signals(
    df: pd.DataFrame,
    config: MeanReversionConfig | None = None,
) -> pd.DataFrame:
    """
    Generate BUY/SELL/HOLD signals from Bollinger Band deviation.

    Entry rule (BUY):
      - close < bb_lower  (price below lower band → oversold, expect reversion)

    Exit rule (SELL):
      - close >= bb_mid   (price reverted to mean — take profit)

    Hold: neither condition met.

    Args:
        df:     DataFrame with feature engineer output including Bollinger Bands.
                Required columns: timestamp, close, bb_upper, bb_mid, bb_lower, atr_14.
        config: MeanReversionConfig with risk parameters.

    Returns:
        Copy of df with additional columns:
          signal          — "BUY" | "SELL" | "HOLD"
          stop_loss       — ATR-based stop price for long position
          z_score_proxy   — (close - bb_mid) / band_half_width, 0 if band_width is 0
    """
    _check_cols(df)
    if config is None:
        config = MeanReversionConfig()

    out = df.copy()

    # Oversold: price below lower Bollinger Band
    oversold = out["close"] < out["bb_lower"]

    # Reverted: price at or above the midline (20-day SMA)
    reverted = out["close"] >= out["bb_mid"]

    out["signal"] = "HOLD"
    out.loc[oversold, "signal"] = "BUY"
    out.loc[reverted, "signal"] = "SELL"   # reversion exit overrides entry

    # ATR stop-loss for long entries
    out["stop_loss"] = out["close"] - config.atr_stop_multiplier * out["atr_14"]

    # Normalised deviation from midband (proxy for z-score given BB construction)
    band_width = (out["bb_upper"] - out["bb_lower"]) / 2.0
    safe_width = band_width.replace(0, float("nan"))
    out["z_score_proxy"] = (out["close"] - out["bb_mid"]) / safe_width
    out["z_score_proxy"] = out["z_score_proxy"].fillna(0.0)

    _log.info(
        f"Generated signals — BUY={oversold.sum()}, SELL={reverted.sum()}, "
        f"HOLD={(~oversold & ~reverted).sum()}, total={len(out)}"
    )
    return out


def compute_position_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    config: MeanReversionConfig | None = None,
) -> int:
    """
    Fixed fractional position sizing: risk / (entry - stop).

    Args:
        capital:     Portfolio capital in USD.
        entry_price: Long entry price.
        stop_loss:   Stop-loss price.
        config:      MeanReversionConfig (defaults if None).

    Returns:
        Number of whole shares (minimum 1). Returns 0 if stop >= entry.
    """
    if config is None:
        config = MeanReversionConfig()

    risk_budget = capital * config.max_risk_per_trade
    price_risk = entry_price - stop_loss

    if price_risk <= 0:
        _log.warning(
            f"Stop ({stop_loss:.2f}) >= entry ({entry_price:.2f}) — position size = 0"
        )
        return 0

    shares = int(risk_budget / price_risk)
    return max(shares, 1)
