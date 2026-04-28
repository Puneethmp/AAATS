"""
US market feature engineer.
Computes technical indicators and return features from validated OHLCV bars.
All features are purely backward-looking; no future data is used at any bar.
"""

from typing import Any

import numpy as np
import pandas as pd
import pandas_ta_classic as pta

from foundation.logger import get_logger

_log = get_logger("us", "feature_engineer")

_REQUIRED_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]

_EXPECTED_OUTPUT_COLUMNS: list[str] = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "return_1d",
    "return_5d",
    "return_20d",
    "return_60d",
    "rsi_14",
    "macd",
    "signal",
    "hist",
    "ema_20",
    "ema_50",
    "ema_200",
    "bb_upper",
    "bb_mid",
    "bb_lower",
    "adx_14",
    "atr_14",
    "hist_vol_20",
    "obv",
    "vol_ratio_20",
]


def calculate_features(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    Compute technical features from validated OHLCV bars.

    All indicators are rolling and backward-looking. The warmup period is
    determined by the longest indicator (EMA-200). Rows where any feature
    is NaN are dropped before returning.

    Args:
        df:     DataFrame with columns [timestamp, open, high, low, close, volume].
                Rows must be in ascending timestamp order (validator guarantee).
        symbol: Ticker symbol — used only for logging.

    Returns:
        DataFrame with original OHLCV columns plus all feature columns.
        Warmup rows (NaN features) are dropped. Index is reset.

    Raises:
        ValueError: If any required column is missing from df.
    """
    _log.info(f"Calculating features for {symbol} — input rows: {len(df)}")

    missing = set(_REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    if df.empty:
        _log.warning(f"{symbol}: empty DataFrame, returning empty")
        return df.copy()

    out = df.copy()

    # ── Returns ───────────────────────────────────────────────────────────────
    out["return_1d"] = out["close"].pct_change(1)
    out["return_5d"] = out["close"].pct_change(5)
    out["return_20d"] = out["close"].pct_change(20)
    out["return_60d"] = out["close"].pct_change(60)

    # ── RSI ───────────────────────────────────────────────────────────────────
    out["rsi_14"] = pta.rsi(out["close"], length=14)

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_df = pta.macd(out["close"])  # default: fast=12, slow=26, signal=9
    out["macd"] = macd_df["MACD_12_26_9"]
    out["signal"] = macd_df["MACDs_12_26_9"]
    out["hist"] = macd_df["MACDh_12_26_9"]

    # ── EMAs ──────────────────────────────────────────────────────────────────
    out["ema_20"] = pta.ema(out["close"], length=20)
    out["ema_50"] = pta.ema(out["close"], length=50)
    out["ema_200"] = pta.ema(out["close"], length=200)

    # ── Bollinger Bands (20, 2σ) ──────────────────────────────────────────────
    bb = pta.bbands(out["close"], length=20)
    out["bb_upper"] = bb["BBU_20_2.0"]
    out["bb_mid"] = bb["BBM_20_2.0"]
    out["bb_lower"] = bb["BBL_20_2.0"]

    # ── ADX ───────────────────────────────────────────────────────────────────
    adx_df = pta.adx(out["high"], out["low"], out["close"], length=14)
    out["adx_14"] = adx_df["ADX_14"]

    # ── ATR ───────────────────────────────────────────────────────────────────
    out["atr_14"] = pta.atr(out["high"], out["low"], out["close"], length=14)

    # ── Historical volatility (annualised, 20-bar window) ─────────────────────
    # Computed from daily returns; sqrt(252) annualises a daily std
    daily_ret = out["close"].pct_change()
    out["hist_vol_20"] = daily_ret.rolling(20).std() * np.sqrt(252)

    # ── OBV ───────────────────────────────────────────────────────────────────
    out["obv"] = pta.obv(out["close"], out["volume"])

    # ── Volume ratio (current bar vs 20-bar rolling mean) ─────────────────────
    vol_sma = out["volume"].rolling(20).mean()
    out["vol_ratio_20"] = out["volume"] / vol_sma

    # ── Drop warmup rows ──────────────────────────────────────────────────────
    feature_cols = [c for c in _EXPECTED_OUTPUT_COLUMNS if c not in _REQUIRED_COLUMNS]
    pre_drop = len(out)
    out = out.dropna(subset=feature_cols).reset_index(drop=True)
    dropped = pre_drop - len(out)

    _log.info(
        f"{symbol}: {len(out)} rows output after dropping {dropped} warmup rows"
    )

    return out[_EXPECTED_OUTPUT_COLUMNS]
