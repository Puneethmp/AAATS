"""
India equity feature engineer.
Computes TA features from validated NSE/BSE OHLCV bars.
Extends the US feature set with India-specific macro inputs (FII/DII, India VIX).
All indicators are purely backward-looking — no lookahead bias.
Warmup NaN rows are retained (not dropped) so callers control their own cutoffs.
"""

from typing import Any

import numpy as np
import pandas as pd
import pandas_ta_classic as pta

from foundation.logger import get_logger

_log = get_logger("india", "feature_engineer")

_REQUIRED_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]

_EXPECTED_OUTPUT_COLUMNS: list[str] = [
    # OHLCV passthrough
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    # Price returns
    "returns_1d",
    "returns_5d",
    "returns_20d",
    "log_return",
    # Momentum
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "roc_10",
    # Trend
    "ema_20",
    "ema_50",
    "ema_200",
    "adx_14",
    "bb_upper",
    "bb_lower",
    "bb_pct",
    # Volume
    "obv",
    "volume_sma_ratio",
    "delivery_pct",
    # Volatility
    "atr_14",
    "hist_vol_20",
    "india_vix",
    # Institutional
    "fii_net",
    "dii_net",
    # Regime placeholder — filled by Phase 8 india_regime.py
    "india_regime",
]


def engineer_features(
    df: pd.DataFrame,
    symbol: str,
    india_vix: float,
    fii_net: float,
    dii_net: float,
    config: Any,
) -> pd.DataFrame:
    """
    Compute TA and macro features for India equity bars.

    Warmup rows are NOT dropped — EMA_200 will be NaN for the first 199 bars,
    ATR for the first 13, etc. Downstream consumers must handle NaN rows.

    Args:
        df:        OHLCV DataFrame from India fetcher/validator.
        symbol:    NSE/BSE ticker — used only for logging.
        india_vix: Current India VIX value (broadcast to every row).
        fii_net:   FII net buy/sell in crores (positive = net buy).
        dii_net:   DII net buy/sell in crores (positive = net buy).
        config:    AppConfig instance (reserved for future threshold reads).

    Returns:
        DataFrame with columns in _EXPECTED_OUTPUT_COLUMNS order.
        For empty input, returns an empty DataFrame with those columns.

    Raises:
        ValueError: If any required OHLCV column is missing from df.
    """
    _log.info(f"Engineering features for {symbol} — input rows: {len(df)}")

    missing = set(_REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    if df.empty:
        _log.warning(f"{symbol}: empty DataFrame — returning empty with schema columns")
        return pd.DataFrame(columns=_EXPECTED_OUTPUT_COLUMNS)

    out = df.copy()

    # ── Price returns ─────────────────────────────────────────────────────────
    out["returns_1d"] = out["close"].pct_change(1)
    out["returns_5d"] = out["close"].pct_change(5)
    out["returns_20d"] = out["close"].pct_change(20)
    out["log_return"] = np.log(out["close"] / out["close"].shift(1))

    # ── Momentum ──────────────────────────────────────────────────────────────
    out["rsi_14"] = pta.rsi(out["close"], length=14)

    macd_df = pta.macd(out["close"])  # fast=12, slow=26, signal=9
    out["macd"] = macd_df["MACD_12_26_9"]
    out["macd_signal"] = macd_df["MACDs_12_26_9"]
    out["macd_hist"] = macd_df["MACDh_12_26_9"]

    out["roc_10"] = pta.roc(out["close"], length=10)

    # ── Trend ─────────────────────────────────────────────────────────────────
    out["ema_20"] = pta.ema(out["close"], length=20)
    out["ema_50"] = pta.ema(out["close"], length=50)
    out["ema_200"] = pta.ema(out["close"], length=200)

    adx_df = pta.adx(out["high"], out["low"], out["close"], length=14)
    out["adx_14"] = adx_df["ADX_14"]

    bb = pta.bbands(out["close"], length=20)
    out["bb_upper"] = bb["BBU_20_2.0"]
    out["bb_lower"] = bb["BBL_20_2.0"]
    out["bb_pct"] = bb["BBP_20_2.0"]

    # ── Volume ────────────────────────────────────────────────────────────────
    out["obv"] = pta.obv(out["close"], out["volume"])
    vol_sma = out["volume"].rolling(20).mean()
    out["volume_sma_ratio"] = out["volume"] / vol_sma

    # delivery_pct: pass through if fetcher provides it, else NaN (rare intraday data)
    if "delivery_pct" not in out.columns:
        out["delivery_pct"] = np.nan

    # ── Volatility ────────────────────────────────────────────────────────────
    out["atr_14"] = pta.atr(out["high"], out["low"], out["close"], length=14)
    daily_ret = out["close"].pct_change()
    out["hist_vol_20"] = daily_ret.rolling(20).std() * np.sqrt(252)
    out["india_vix"] = india_vix

    # ── Institutional ─────────────────────────────────────────────────────────
    out["fii_net"] = fii_net
    out["dii_net"] = dii_net

    # ── Regime placeholder ────────────────────────────────────────────────────
    out["india_regime"] = np.nan

    _log.info(f"{symbol}: feature engineering complete — {len(out)} rows")
    return out[_EXPECTED_OUTPUT_COLUMNS]
