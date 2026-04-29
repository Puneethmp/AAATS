"""
US Momentum Strategy.

Entry signal:  EMA50 > EMA200 (golden cross / uptrend) AND momentum filter
               (5-day return > 0 AND close above EMA50).
Exit signal:   EMA50 < EMA200 (death cross / downtrend) OR ATR stop-loss breach.
Position size: Fixed fractional based on ATR (1.5% risk per trade max).

Produces a column "signal" with values: "BUY", "SELL", or "HOLD".
ATR stop loss levels are returned alongside signals for the execution layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from foundation.logger import get_logger

_log = get_logger("us", "momentum")

_REQUIRED_COLS = {
    "timestamp", "close", "ema_50", "ema_200", "return_5d", "atr_14",
}


@dataclass(frozen=True)
class MomentumConfig:
    max_risk_per_trade: float = 0.015  # 1.5% of capital per trade
    atr_stop_multiplier: float = 2.0   # stop = entry - 2x ATR
    min_adx: float = 0.0               # optional ADX filter (0 = disabled)


def _check_cols(df: pd.DataFrame) -> None:
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"momentum strategy: missing columns {sorted(missing)}")


def generate_signals(
    df: pd.DataFrame,
    config: MomentumConfig | None = None,
) -> pd.DataFrame:
    """
    Generate BUY/SELL/HOLD signals from feature-engineered OHLCV data.

    Entry rule (BUY):
      - EMA50 > EMA200  (golden cross / trend confirmation)
      - 5-day return > 0  (recent positive momentum)
      - close > EMA50  (price above short-term trend)

    Exit rule (SELL):
      - EMA50 < EMA200  (death cross / downtrend starts)

    Hold:  Neither entry nor exit conditions met.

    Stop-loss levels are computed but NOT applied here — the execution layer
    checks them tick-by-tick against live prices.

    Args:
        df:     DataFrame with columns from US feature engineer output.
                Minimum required: timestamp, close, ema_50, ema_200,
                return_5d, atr_14.
        config: MomentumConfig with risk parameters (uses defaults if None).

    Returns:
        Copy of df with additional columns:
          signal      — "BUY" | "SELL" | "HOLD"
          stop_loss   — price level at which a long position should be closed
                        (entry_close - atr_stop_multiplier * atr_14)
          signal_strength — float 0-1 (fraction of 3 entry conditions met)
    """
    _check_cols(df)
    if config is None:
        config = MomentumConfig()

    out = df.copy()

    # Golden cross: EMA50 crosses above EMA200
    ema_uptrend = out["ema_50"] > out["ema_200"]

    # Momentum filter: 5-day return positive
    momentum_positive = out["return_5d"] > 0

    # Price above short-term trend
    price_above_ema50 = out["close"] > out["ema_50"]

    # Entry: all three conditions
    entry = ema_uptrend & momentum_positive & price_above_ema50

    # Exit: death cross (EMA50 crosses below EMA200)
    exit_ = out["ema_50"] < out["ema_200"]

    # Signal: BUY if entry, SELL if exit (exit takes priority over entry on same bar)
    conditions_met = (
        ema_uptrend.astype(int)
        + momentum_positive.astype(int)
        + price_above_ema50.astype(int)
    )

    out["signal_strength"] = conditions_met / 3.0
    out["signal"] = "HOLD"
    out.loc[entry, "signal"] = "BUY"
    out.loc[exit_, "signal"] = "SELL"  # exit overrides entry

    # Stop-loss: entry price minus ATR buffer
    out["stop_loss"] = out["close"] - config.atr_stop_multiplier * out["atr_14"]

    _log.info(
        f"Generated signals — BUY={entry.sum()}, SELL={exit_.sum()}, "
        f"HOLD={(~entry & ~exit_).sum()}, total={len(out)}"
    )
    return out


def compute_position_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    config: MomentumConfig | None = None,
) -> int:
    """
    Compute number of shares to buy based on fixed fractional position sizing.

    Risk per trade = capital * max_risk_per_trade
    Shares = risk / (entry_price - stop_loss)

    Args:
        capital:     Total portfolio capital in USD.
        entry_price: Price at which the position is entered.
        stop_loss:   ATR-based stop-loss price.
        config:      MomentumConfig (uses defaults if None).

    Returns:
        Number of whole shares to buy (minimum 1, 0 if risk distance is zero).
    """
    if config is None:
        config = MomentumConfig()

    risk_per_trade = capital * config.max_risk_per_trade
    price_risk = entry_price - stop_loss

    if price_risk <= 0:
        _log.warning(
            f"Stop loss ({stop_loss:.2f}) >= entry ({entry_price:.2f}) — position size = 0"
        )
        return 0

    shares = int(risk_per_trade / price_risk)
    return max(shares, 1)
