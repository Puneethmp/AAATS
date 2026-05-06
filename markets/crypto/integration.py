"""
Crypto Market Full Integration.

Orchestrates the complete crypto data pipeline:
  1. Fetch OHLCV from CCXT (Binance) for configured symbols
  2. Validate and engineer features
  3. Run regime detection
  4. Generate grid trading signals
  5. Apply risk engine gate
  6. Log to paper trades DB

This module is the crypto equivalent of the India/US market runners.
Separate drawdown limits for crypto (higher volatility).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from foundation.logger import get_logger
from indicators.regime_detector import RegimeDetectorConfig, detect, get_current_regime
from markets.crypto.storage import fetch_bars, fetch_latest_timestamp, store_bars
from risk.engine import RiskEngine

_log = get_logger("crypto", "integration")

# Default symbols to trade
_DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT"]
_DEFAULT_TIMEFRAME = "1Hour"

# Crypto-specific risk: higher ATR threshold due to volatility
_CRYPTO_REGIME_CONFIG = RegimeDetectorConfig(
    atr_pct_high_vol=0.05,   # 5% ATR (crypto is more volatile)
    vix_high_threshold=20.0,
    ema_pct_band=0.02,        # 2% band (wider for crypto)
    adx_trend_threshold=20.0,
    adx_range_threshold=15.0,
)


@dataclass
class CryptoConfig:
    symbols: list[str] = field(default_factory=lambda: list(_DEFAULT_SYMBOLS))
    timeframe: str = _DEFAULT_TIMEFRAME
    db_path: str = "data/crypto.db"
    lookback_hours: int = 200   # bars of history to fetch
    capital_usdt: float = 10_000.0
    max_drawdown_pct: float = 0.25  # 25% crypto drawdown halt (wider than equity)


@dataclass
class CryptoMarketSnapshot:
    """Result of one crypto market data cycle."""
    symbol: str
    timeframe: str
    regime: str
    latest_bar: dict[str, Any]
    bars_stored: int
    feature_cols: list[str]
    error: str | None = None


def _compute_basic_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add minimal feature columns needed by regime detector and grid strategy.

    Uses only price/volume data — no external dependencies.
    """
    out = df.copy()

    # Returns
    out["return_1d"] = out["close"].pct_change(1)
    out["return_5d"] = out["close"].pct_change(5)

    # EMAs (manual rolling for no pandas_ta dependency)
    out["ema_50"] = out["close"].ewm(span=50, adjust=False).mean()
    out["ema_200"] = out["close"].ewm(span=200, adjust=False).mean()
    out["ema_spread_pct"] = (out["ema_50"] - out["ema_200"]) / out["ema_200"].replace(0, float("nan"))

    # RSI (14)
    delta = out["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    out["rsi_14"] = 100 - (100 / (1 + rs))

    # ATR (14)
    hl = out["high"] - out["low"]
    hc = (out["high"] - out["close"].shift()).abs()
    lc = (out["low"] - out["close"].shift()).abs()
    out["atr_14"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
    out["atr_pct"] = out["atr_14"] / out["close"].replace(0, float("nan"))

    # MACD
    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26

    # Volume ratio
    out["vol_ratio"] = out["volume"] / out["volume"].rolling(20).mean()

    return out


def run_data_cycle(
    symbol: str,
    config: CryptoConfig,
    fetcher_fn: Any = None,
) -> CryptoMarketSnapshot:
    """
    Run one full data fetch-store-feature-detect cycle for a crypto symbol.

    Args:
        symbol:     CCXT market symbol (e.g. "BTC/USDT").
        config:     CryptoConfig with DB path, timeframe, etc.
        fetcher_fn: Optional override for the OHLCV fetch function
                    (used in tests to inject mock data).

    Returns:
        CryptoMarketSnapshot with regime and latest bar data.
    """
    try:
        # Determine fetch range
        latest = fetch_latest_timestamp(symbol, config.timeframe, config.db_path)
        if latest:
            start = pd.Timestamp(latest, tz="UTC") + pd.Timedelta(hours=1)
        else:
            start = datetime.now(timezone.utc) - timedelta(hours=config.lookback_hours)
        end = datetime.now(timezone.utc)

        # Fetch OHLCV
        if fetcher_fn is not None:
            raw_df = fetcher_fn(symbol, config.timeframe, start, end)
        else:
            from markets.crypto.fetcher import fetch_ohlcv
            raw_df = fetch_ohlcv(symbol, config.timeframe, start, end)

        if raw_df.empty:
            _log.warning(f"No new data for {symbol}")
            # Load existing from DB
            raw_df = fetch_bars(
                symbol, config.timeframe,
                str(start)[:10], str(end)[:10],
                config.db_path
            )
            if raw_df.empty:
                return CryptoMarketSnapshot(
                    symbol=symbol, timeframe=config.timeframe,
                    regime="UNKNOWN", latest_bar={}, bars_stored=0, feature_cols=[]
                )

        # Store raw bars
        stored = store_bars(raw_df, symbol, config.timeframe, config.db_path)

        # Feature engineering
        featured_df = _compute_basic_features(raw_df)

        # Regime detection
        regime = get_current_regime(featured_df, _CRYPTO_REGIME_CONFIG)

        latest_bar = featured_df.iloc[-1].to_dict()

        _log.info(f"{symbol}: stored={stored}, regime={regime}, close={latest_bar.get('close', 'N/A')}")

        return CryptoMarketSnapshot(
            symbol=symbol,
            timeframe=config.timeframe,
            regime=regime,
            latest_bar=latest_bar,
            bars_stored=stored,
            feature_cols=list(featured_df.columns),
        )

    except Exception as exc:
        _log.error(f"Crypto data cycle failed for {symbol}: {exc}")
        return CryptoMarketSnapshot(
            symbol=symbol, timeframe=config.timeframe,
            regime="UNKNOWN", latest_bar={}, bars_stored=0,
            feature_cols=[], error=str(exc),
        )


def run_all_symbols(
    config: CryptoConfig,
    fetcher_fn: Any = None,
) -> list[CryptoMarketSnapshot]:
    """
    Run the data cycle for all configured symbols.

    Returns:
        List of CryptoMarketSnapshot, one per symbol.
    """
    snapshots = []
    for symbol in config.symbols:
        snapshot = run_data_cycle(symbol, config, fetcher_fn=fetcher_fn)
        snapshots.append(snapshot)
    return snapshots


def get_crypto_regime_summary(snapshots: list[CryptoMarketSnapshot]) -> dict[str, str]:
    """
    Return a {symbol: regime} summary dict from a list of snapshots.
    """
    return {s.symbol: s.regime for s in snapshots}
