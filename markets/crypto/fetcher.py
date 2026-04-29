"""
Crypto market data fetcher using CCXT (exchange OHLCV) and CoinGecko (price/metadata).

Primary source: CCXT with Binance exchange (no API key needed for public OHLCV).
Fallback source: CoinGecko REST API for coins without exchange listings.

Retries with exponential backoff (6 attempts). Halts crypto market after exhaustion.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import ccxt
import pandas as pd
import requests

from foundation.logger import get_logger

_log = get_logger("crypto", "fetcher")

_BACKOFF_DELAYS: list[int] = [1, 2, 4, 8, 16]

_CCXT_TIMEFRAME_MAP: dict[str, str] = {
    "1Day": "1d",
    "1Hour": "1h",
    "15Min": "15m",
    "5Min": "5m",
    "1Min": "1m",
}

_COINGECKO_BASE = "https://api.coingecko.com/api/v3"
_COINGECKO_DAYS_FOR_HOURLY = 90  # CoinGecko returns hourly data for <= 90 days


def _with_backoff(fn: Any, label: str) -> Any:
    for attempt, delay in enumerate(_BACKOFF_DELAYS, start=1):
        try:
            return fn()
        except Exception as exc:
            _log.warning(f"{label} attempt {attempt}/6 failed: {exc}")
            time.sleep(delay)
    try:
        return fn()
    except Exception as exc:
        _log.error(f"{label} — all 6 attempts exhausted: {exc}")
        raise


def _build_exchange(exchange_id: str = "binance") -> ccxt.Exchange:
    exchange_class = getattr(ccxt, exchange_id)
    return exchange_class({"enableRateLimit": True})


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    exchange_id: str = "binance",
    limit: int = 1000,
) -> pd.DataFrame:
    """
    Fetch historical OHLCV bars for a crypto symbol from a CCXT-supported exchange.

    Args:
        symbol:      CCXT market symbol (e.g. "BTC/USDT").
        timeframe:   Bar size — "1Day", "1Hour", "15Min", "5Min", "1Min".
        start:       Start datetime (UTC-aware or naive UTC).
        end:         End datetime (UTC-aware or naive UTC).
        exchange_id: CCXT exchange name (default: "binance").
        limit:       Max bars per request (exchange-specific ceiling).

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].
        Timestamps are UTC-aware pandas Timestamps.
        Empty DataFrame if the exchange returns no data for the range.

    Raises:
        ValueError:  If timeframe is unsupported.
        Exception:   After 6 consecutive failures.
    """
    if timeframe not in _CCXT_TIMEFRAME_MAP:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. "
            f"Valid values: {list(_CCXT_TIMEFRAME_MAP)}"
        )

    ccxt_tf = _CCXT_TIMEFRAME_MAP[timeframe]

    def _to_ms(dt: datetime) -> int:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)

    since_ms = _to_ms(start)
    end_ms = _to_ms(end)

    def _fetch() -> pd.DataFrame:
        exchange = _build_exchange(exchange_id)
        all_rows: list[list] = []
        current_since = since_ms

        while True:
            raw = exchange.fetch_ohlcv(
                symbol, ccxt_tf, since=current_since, limit=limit
            )
            if not raw:
                break
            # Filter rows beyond end
            filtered = [r for r in raw if r[0] <= end_ms]
            all_rows.extend(filtered)
            if len(filtered) < len(raw) or len(raw) < limit:
                break
            current_since = raw[-1][0] + 1  # advance past last fetched

        if not all_rows:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        df = pd.DataFrame(
            all_rows,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df.sort_values("timestamp").reset_index(drop=True)

    _log.info(f"Fetching {timeframe} OHLCV for {symbol} from {exchange_id}")
    return _with_backoff(_fetch, f"CCXT {symbol}")


def fetch_coingecko_ohlc(
    coin_id: str,
    vs_currency: str = "usd",
    days: int = 30,
) -> pd.DataFrame:
    """
    Fetch OHLC data from CoinGecko's public API.

    Granularity is automatic: 1 day for > 90 days, 1 hour for <= 90 days.

    Args:
        coin_id:     CoinGecko coin ID (e.g. "bitcoin", "ethereum").
        vs_currency: Quote currency (default: "usd").
        days:        Number of days of history to fetch (1-max).

    Returns:
        DataFrame with columns [timestamp, open, high, low, close].
        No volume column (CoinGecko OHLC endpoint does not include volume).
        Timestamps are UTC-aware pandas Timestamps.

    Raises:
        requests.HTTPError: On non-2xx response after retries.
        Exception:          After 6 consecutive failures.
    """
    url = f"{_COINGECKO_BASE}/coins/{coin_id}/ohlc"
    params = {"vs_currency": vs_currency, "days": str(days)}

    def _fetch() -> pd.DataFrame:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close"]
            )
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df.sort_values("timestamp").reset_index(drop=True)

    _log.info(f"Fetching {days}d OHLC for {coin_id} from CoinGecko")
    return _with_backoff(_fetch, f"CoinGecko {coin_id}")


def fetch_coingecko_price(
    coin_ids: list[str],
    vs_currencies: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    """
    Fetch current prices for one or more coins from CoinGecko.

    Args:
        coin_ids:      List of CoinGecko coin IDs (e.g. ["bitcoin", "ethereum"]).
        vs_currencies: List of quote currencies (default: ["usd"]).

    Returns:
        Nested dict: {coin_id: {currency: price}}.
        Example: {"bitcoin": {"usd": 65000.0}}.

    Raises:
        requests.HTTPError: On non-2xx response after retries.
    """
    if vs_currencies is None:
        vs_currencies = ["usd"]

    url = f"{_COINGECKO_BASE}/simple/price"
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": ",".join(vs_currencies),
    }

    def _fetch() -> dict[str, dict[str, float]]:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    _log.info(f"Fetching prices for {coin_ids}")
    return _with_backoff(_fetch, f"CoinGecko prices")


def fetch_coingecko_market_data(coin_id: str) -> dict[str, Any]:
    """
    Fetch market metadata for a coin (market cap, volume 24h, rank, etc.).

    Args:
        coin_id: CoinGecko coin ID (e.g. "bitcoin").

    Returns:
        Dict with market_cap, total_volume, current_price, market_cap_rank, etc.
        Returns empty dict on failure after retries.
    """
    url = f"{_COINGECKO_BASE}/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": coin_id,
        "order": "market_cap_desc",
        "per_page": 1,
        "page": 1,
    }

    def _fetch() -> dict[str, Any]:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else {}

    _log.info(f"Fetching market data for {coin_id}")
    return _with_backoff(_fetch, f"CoinGecko market data {coin_id}")
