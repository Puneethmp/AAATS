"""
India Momentum Strategy.

Entry signal:  Nifty/stock EMA50 > EMA200 (uptrend) AND India VIX < vix_threshold
               (low volatility regime) AND 5-day return positive.
Exit signal:   EMA50 < EMA200 (downtrend starts) OR India VIX spikes above threshold.
Position size: Fixed fractional with ATR stop.

India-specific considerations:
- India VIX > 20 → market is stressed → no new longs.
- F&O expiry weeks have elevated volatility; the VIX gate handles this.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import numpy as np

from foundation.logger import get_logger

_log = get_logger("india", "momentum")

_REQUIRED_COLS = {
    "timestamp", "close", "ema_50", "ema_200", "returns_5d", "atr_14", "india_vix",
}


@dataclass(frozen=True)
class IndiaMomentumConfig:
    max_risk_per_trade: float = 0.015   # 1.5% risk cap (NSE equity)
    atr_stop_multiplier: float = 2.0
    vix_threshold: float = 20.0         # India VIX above this → no new longs


def _check_cols(df: pd.DataFrame) -> None:
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"india momentum strategy: missing columns {sorted(missing)}")


def generate_signals(
    df: pd.DataFrame,
    config: IndiaMomentumConfig | None = None,
) -> pd.DataFrame:
    """
    Generate BUY/SELL/HOLD signals for India equity using EMA crossover + VIX gate.

    Entry rule (BUY) — ALL must hold:
      - EMA50 > EMA200  (golden cross)
      - india_vix < vix_threshold  (market not stressed)
      - returns_5d > 0  (positive near-term momentum)
      - close > EMA50   (price above short-term trend)

    Exit rule (SELL) — ANY triggers exit:
      - EMA50 < EMA200  (death cross)
      - india_vix >= vix_threshold  (market stress spike)

    Args:
        df:     Feature-engineered DataFrame with India-specific columns.
        config: IndiaMomentumConfig with risk/VIX parameters.

    Returns:
        Copy of df with columns:
          signal          — "BUY" | "SELL" | "HOLD"
          stop_loss       — entry close - atr_stop_multiplier * atr_14
          vix_blocked     — bool: True if VIX gate blocked a potential BUY
    """
    _check_cols(df)
    if config is None:
        config = IndiaMomentumConfig()

    out = df.copy()

    ema_uptrend = out["ema_50"] > out["ema_200"]
    vix_ok = out["india_vix"] < config.vix_threshold
    momentum_positive = out["returns_5d"] > 0
    price_above_ema50 = out["close"] > out["ema_50"]

    entry = ema_uptrend & vix_ok & momentum_positive & price_above_ema50

    # Exit: death cross OR VIX spike
    ema_downtrend = out["ema_50"] < out["ema_200"]
    vix_spike = out["india_vix"] >= config.vix_threshold
    exit_ = ema_downtrend | vix_spike

    # Would have been BUY but VIX blocked it
    out["vix_blocked"] = ema_uptrend & ~vix_ok & momentum_positive & price_above_ema50

    out["signal"] = "HOLD"
    out.loc[entry, "signal"] = "BUY"
    out.loc[exit_, "signal"] = "SELL"  # exit overrides entry

    out["stop_loss"] = out["close"] - config.atr_stop_multiplier * out["atr_14"]

    buy_count = (out["signal"] == "BUY").sum()
    sell_count = (out["signal"] == "SELL").sum()
    vix_blocked_count = out["vix_blocked"].sum()
    _log.info(
        f"Signals — BUY={buy_count}, SELL={sell_count}, "
        f"VIX_BLOCKED={vix_blocked_count}, total={len(out)}"
    )
    return out


def compute_position_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    config: IndiaMomentumConfig | None = None,
) -> int:
    """
    Fixed fractional position sizing for India equity.

    Returns number of whole shares. Returns 0 if stop >= entry.
    """
    if config is None:
        config = IndiaMomentumConfig()

    risk_budget = capital * config.max_risk_per_trade
    price_risk = entry_price - stop_loss

    if price_risk <= 0:
        _log.warning(f"Stop ({stop_loss:.2f}) >= entry ({entry_price:.2f}) — size=0")
        return 0

    return max(int(risk_budget / price_risk), 1)
