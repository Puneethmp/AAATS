"""
Centralized Feature Engineering Pipeline
==========================================
Why this exists
---------------
Every strategy in AAATS expects pre-computed features (EMA_50, ATR_14, RSI_14, etc.)
but there was no single module responsible for computing them. Each strategy was
either given pre-computed DataFrames of uncertain provenance or computed features
inline with inconsistent parameters. This module is THE authoritative source.

All features are computed in a single vectorized pass over raw OHLCV data.
No external TA library dependency — pure pandas/numpy for portability.

Feature Set
-----------
Trend:
  ema_9, ema_21, ema_50, ema_200     — Exponential Moving Averages
  sma_20, sma_50                     — Simple Moving Averages
  macd, macd_signal, macd_hist       — MACD (12/26/9)
  supertrend_10_3                    — Supertrend (period=10, mult=3)

Momentum:
  rsi_14                             — Relative Strength Index (14)
  rsi_9                              — Fast RSI (9)
  return_1, return_5, return_20      — Log returns at multiple lags
  mom_10                             — 10-bar price momentum (%)

Volatility:
  atr_14                             — Average True Range (14)
  atr_pct                            — ATR as % of close (normalised)
  bb_upper, bb_mid, bb_lower         — Bollinger Bands (20, 2σ)
  bb_pct                             — %B (position within bands)
  bb_width                           — Band width (volatility proxy)
  hist_vol_20                        — 20-bar historical volatility (ann.)
  hist_vol_60                        — 60-bar historical volatility (ann.)

Volume:
  vwap                               — VWAP (session, resets each day)
  vol_z                              — Volume z-score (20-bar)
  vol_ratio                          — Volume / 20-bar average volume

Trend Strength:
  adx_14                             — Average Directional Index (14)
  plus_di_14, minus_di_14            — Directional indicators

Cross-market derived:
  regime_ema_spread                  — (EMA50 - EMA200) / close

Usage
-----
  from indicators.features import FeaturePipeline

  pipeline = FeaturePipeline()
  df_features = pipeline.compute(df_ohlcv)   # df must have: open,high,low,close,volume

  # Or per-feature group
  df = pipeline.add_trend(df)
  df = pipeline.add_momentum(df)
  df = pipeline.add_volatility(df)
  df = pipeline.add_volume(df)
  df = pipeline.add_trend_strength(df)
"""

from __future__ import annotations

import warnings
from typing import Sequence

import numpy as np
import pandas as pd

__all__ = ["FeaturePipeline", "compute_features", "FEATURE_COLUMNS"]

# Canonical list of all feature columns produced by the full pipeline
FEATURE_COLUMNS: list[str] = [
    # Trend
    "ema_9", "ema_21", "ema_50", "ema_200", "sma_20", "sma_50",
    "macd", "macd_signal", "macd_hist",
    # Momentum
    "rsi_14", "rsi_9", "return_1", "return_5", "return_20", "mom_10",
    # Volatility
    "atr_14", "atr_pct",
    "bb_upper", "bb_mid", "bb_lower", "bb_pct", "bb_width",
    "hist_vol_20", "hist_vol_60",
    # Volume
    "vwap", "vol_z", "vol_ratio",
    # Trend strength
    "adx_14", "plus_di_14", "minus_di_14",
    # Derived
    "regime_ema_spread",
]

_REQUIRED_COLS = {"open", "high", "low", "close", "volume"}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=1).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)  # neutral on warmup


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=1, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    """Returns DataFrame with adx_14, plus_di_14, minus_di_14."""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    plus_dm = (high - prev_high).clip(lower=0.0)
    minus_dm = (prev_low - low).clip(lower=0.0)
    # When both positive, take the larger
    both_positive = (plus_dm > 0) & (minus_dm > 0)
    plus_dm[both_positive & (minus_dm >= plus_dm)] = 0.0
    minus_dm[both_positive & (plus_dm > minus_dm)] = 0.0

    atr = _atr(high, low, close, period)

    smoothed_plus = plus_dm.ewm(com=period - 1, min_periods=1, adjust=False).mean()
    smoothed_minus = minus_dm.ewm(com=period - 1, min_periods=1, adjust=False).mean()

    plus_di = 100.0 * smoothed_plus / atr.replace(0, np.nan).fillna(1.0)
    minus_di = 100.0 * smoothed_minus / atr.replace(0, np.nan).fillna(1.0)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan).fillna(1.0)
    adx = dx.ewm(com=period - 1, min_periods=1, adjust=False).mean()

    return pd.DataFrame(
        {"adx_14": adx, "plus_di_14": plus_di, "minus_di_14": minus_di},
        index=high.index,
    )


def _vwap(df: pd.DataFrame) -> pd.Series:
    """
    Session VWAP. Resets at each day boundary if DatetimeIndex is available.
    Falls back to cumulative VWAP if index is not datetime.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    dollar_vol = typical * df["volume"]

    if isinstance(df.index, pd.DatetimeIndex):
        date = df.index.date
        groups = pd.Series(date, index=df.index)
        cum_dv = dollar_vol.groupby(groups).cumsum()
        cum_vol = df["volume"].groupby(groups).cumsum()
    else:
        cum_dv = dollar_vol.cumsum()
        cum_vol = df["volume"].cumsum()

    return (cum_dv / cum_vol.replace(0, np.nan)).fillna(typical)


# ---------------------------------------------------------------------------
# FeaturePipeline
# ---------------------------------------------------------------------------

class FeaturePipeline:
    """
    Computes all AAATS features from raw OHLCV in a single pass.

    Parameters
    ----------
    annualise_factor    Bars per year for volatility annualisation.
                        252 for daily, 252*6.5 for US 1-hour, 365*24 for crypto.
    fillna              If True (default), forward-fill NaNs from warmup periods.
    """

    def __init__(
        self,
        annualise_factor: float = 252.0,
        fillna: bool = True,
    ):
        self.annualise_factor = annualise_factor
        self.fillna = fillna

    # ------------------------------------------------------------------
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Full feature computation. Returns df with all FEATURE_COLUMNS appended.

        Parameters
        ----------
        df      Raw OHLCV DataFrame. Must contain: open, high, low, close, volume.
                Column names are case-insensitive.
        """
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        missing = _REQUIRED_COLS - set(df.columns)
        if missing:
            raise ValueError(f"FeaturePipeline: missing columns {sorted(missing)}")

        # Ensure float, forward-fill any price gaps
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce").ffill()
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)

        df = self.add_trend(df)
        df = self.add_momentum(df)
        df = self.add_volatility(df)
        df = self.add_volume(df)
        df = self.add_trend_strength(df)
        df = self._add_derived(df)

        if self.fillna:
            for col in FEATURE_COLUMNS:
                if col in df.columns:
                    df[col] = df[col].ffill().bfill()

        return df

    # ------------------------------------------------------------------
    def add_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        df["ema_9"] = _ema(close, 9)
        df["ema_21"] = _ema(close, 21)
        df["ema_50"] = _ema(close, 50)
        df["ema_200"] = _ema(close, 200)
        df["sma_20"] = _sma(close, 20)
        df["sma_50"] = _sma(close, 50)

        # MACD: 12/26 EMA diff, signal=9 EMA of MACD
        ema_12 = _ema(close, 12)
        ema_26 = _ema(close, 26)
        df["macd"] = ema_12 - ema_26
        df["macd_signal"] = _ema(df["macd"], 9)
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        return df

    # ------------------------------------------------------------------
    def add_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"]
        log_ret = np.log(close / close.shift(1))

        df["rsi_14"] = _rsi(close, 14)
        df["rsi_9"] = _rsi(close, 9)
        df["return_1"] = log_ret
        df["return_5"] = np.log(close / close.shift(5))
        df["return_20"] = np.log(close / close.shift(20))
        df["mom_10"] = (close / close.shift(10) - 1.0) * 100.0  # % momentum

        return df

    # ------------------------------------------------------------------
    def add_volatility(self, df: pd.DataFrame) -> pd.DataFrame:
        high, low, close = df["high"], df["low"], df["close"]

        df["atr_14"] = _atr(high, low, close, 14)
        df["atr_pct"] = df["atr_14"] / close.replace(0, np.nan)

        # Bollinger Bands (20, 2σ)
        df["bb_mid"] = _sma(close, 20)
        rolling_std = close.rolling(20, min_periods=5).std()
        df["bb_upper"] = df["bb_mid"] + 2.0 * rolling_std
        df["bb_lower"] = df["bb_mid"] - 2.0 * rolling_std
        band_width = (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)
        df["bb_pct"] = (close - df["bb_lower"]) / band_width
        df["bb_width"] = band_width / df["bb_mid"].replace(0, np.nan)

        # Historical volatility (annualised)
        log_ret = np.log(close / close.shift(1))
        ann = np.sqrt(self.annualise_factor)
        df["hist_vol_20"] = log_ret.rolling(20, min_periods=10).std() * ann
        df["hist_vol_60"] = log_ret.rolling(60, min_periods=20).std() * ann

        return df

    # ------------------------------------------------------------------
    def add_volume(self, df: pd.DataFrame) -> pd.DataFrame:
        vol = df["volume"]
        vol_ma = _sma(vol, 20).replace(0, np.nan)
        vol_std = vol.rolling(20, min_periods=5).std().replace(0, np.nan)

        df["vwap"] = _vwap(df)
        df["vol_z"] = (vol - vol_ma) / vol_std
        df["vol_ratio"] = vol / vol_ma

        return df

    # ------------------------------------------------------------------
    def add_trend_strength(self, df: pd.DataFrame) -> pd.DataFrame:
        adx_df = _adx(df["high"], df["low"], df["close"], 14)
        df["adx_14"] = adx_df["adx_14"]
        df["plus_di_14"] = adx_df["plus_di_14"]
        df["minus_di_14"] = adx_df["minus_di_14"]
        return df

    # ------------------------------------------------------------------
    def _add_derived(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].replace(0, np.nan)
        df["regime_ema_spread"] = (df["ema_50"] - df["ema_200"]) / close
        return df


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def compute_features(
    df: pd.DataFrame,
    annualise_factor: float = 252.0,
    fillna: bool = True,
) -> pd.DataFrame:
    """
    One-shot feature computation from raw OHLCV.

    Example
    -------
    from indicators.features import compute_features
    df_feat = compute_features(df_ohlcv)
    """
    return FeaturePipeline(annualise_factor=annualise_factor, fillna=fillna).compute(df)
