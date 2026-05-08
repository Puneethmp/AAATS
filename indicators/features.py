"""
Canonical feature pipeline used by both training and inference.

Adds: ema_50, ema_200, ema_spread_pct, rsi_14, atr_14, macd, adx_14.

Mirrors execution/india_runner._compute_features for the basic indicators,
extended with MACD and ADX_14 which the model feature lists require.

If you add a feature here, also add it (or its mapping) to whichever caller
needs it: trading/live_paper_runner.py for inference, ml/train_from_history.py
for the training derivation step.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    OHLCV -> enriched feature DataFrame.

    Args:
        df: DataFrame with columns: open, high, low, close, volume.
            Index should be a DatetimeIndex sorted ascending.

    Returns:
        Copy of df with feature columns appended.
    """
    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]

    # ── EMAs and EMA spread ───────────────────────────────────────────────────
    out["ema_50"] = close.ewm(span=50, adjust=False).mean()
    out["ema_200"] = close.ewm(span=200, adjust=False).mean()
    out["ema_spread_pct"] = (
        (out["ema_50"] - out["ema_200"]) / out["ema_200"].replace(0, float("nan"))
    )

    # ── RSI(14) — Wilder's smoothing approximated by simple rolling mean ──────
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    out["rsi_14"] = 100 - (100 / (1 + rs))

    # ── True Range and ATR(14) ────────────────────────────────────────────────
    hl = high - low
    hc = (high - close.shift()).abs()
    lc = (low - close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    out["atr_14"] = tr.rolling(14).mean()

    # ── MACD (12/26 EMA difference) ──────────────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26

    # ── ADX(14) with Wilder's smoothing ───────────────────────────────────────
    up_move = high.diff()
    down_move = -low.diff()  # positive when low fell
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=out.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=out.index
    )
    # Wilder's smoothing = exponential with alpha=1/n
    alpha = 1.0 / 14
    tr_smooth = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=alpha, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * plus_dm_smooth / tr_smooth.replace(0, float("nan"))
    minus_di = 100 * minus_dm_smooth / tr_smooth.replace(0, float("nan"))
    di_sum = (plus_di + minus_di).replace(0, float("nan"))
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    out["adx_14"] = dx.ewm(alpha=alpha, adjust=False).mean()

    return out
