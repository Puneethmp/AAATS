"""tools/backtest/historical_data.py - fetch + cache Binance OHLCV bars.

Uses ccxt.binance() public REST (no auth needed for historical klines).
Cache lives at data/historical/<symbol_slug>_<timeframe>.parquet so reruns
of the harness don't re-fetch.

Public API:
    fetch_ohlcv(symbol, timeframe, days_back, end_ts=None) -> pd.DataFrame
        Returns a DataFrame with columns ts, open, high, low, close, volume.
        ts is timezone-aware UTC.
"""
from __future__ import annotations

import datetime as _dt
import logging
import pathlib
import time
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CACHE_DIR = _ROOT / "data" / "historical"

_TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def _slug(symbol: str) -> str:
    return symbol.replace("/", "_").replace(":", "_")


def _cache_path(symbol: str, timeframe: str) -> pathlib.Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{_slug(symbol)}_{timeframe}.parquet"


def _fetch_via_ccxt(
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
) -> pd.DataFrame:
    """Pull [since_ms, until_ms) bars from Binance via ccxt, paging by 1000."""
    import ccxt

    ex = ccxt.binance({"enableRateLimit": True})
    tf_ms = _TIMEFRAME_MS[timeframe]
    limit = 1000

    rows: list[list] = []
    cursor = since_ms
    while cursor < until_ms:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        last_ts = batch[-1][0]
        # advance past last bar to avoid infinite loop on duplicate boundary
        cursor = last_ts + tf_ms
        if len(batch) < limit:
            break
        # gentle to the API
        time.sleep(ex.rateLimit / 1000.0)

    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    return df[(df["ts"] >= pd.Timestamp(since_ms, unit="ms", tz="UTC"))
              & (df["ts"] < pd.Timestamp(until_ms, unit="ms", tz="UTC"))]


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    days_back: int = 60,
    end_ts: Optional[_dt.datetime] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Return OHLCV bars for [end_ts - days_back, end_ts).

    Caches the full requested window per (symbol, timeframe). If the cache
    already covers the request, returns the cached slice; otherwise
    re-fetches the full window. (We do NOT incrementally extend — the
    request window for B.1.5 is fixed at "last N days" and re-running
    against a different end_ts is rare enough that simple cache-or-fetch
    semantics are cleaner.)
    """
    if timeframe not in _TIMEFRAME_MS:
        raise ValueError(f"unsupported timeframe {timeframe!r}; "
                         f"choose from {sorted(_TIMEFRAME_MS)}")
    if end_ts is None:
        end_ts = _dt.datetime.now(_dt.timezone.utc)
    elif end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=_dt.timezone.utc)

    until_ms = int(end_ts.timestamp() * 1000)
    since_ms = until_ms - days_back * 86_400_000

    cache = _cache_path(symbol, timeframe)
    if cache.exists() and not force_refresh:
        try:
            df = pd.read_parquet(cache)
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            covered_since = df["ts"].min()
            covered_until = df["ts"].max()
            need_since = pd.Timestamp(since_ms, unit="ms", tz="UTC")
            need_until = pd.Timestamp(until_ms, unit="ms", tz="UTC")
            # Cache covers if it starts before need_since and ends after
            # (need_until - one bar of tolerance for in-progress current bar).
            tf_ms = _TIMEFRAME_MS[timeframe]
            tol = pd.Timedelta(milliseconds=tf_ms)
            if covered_since <= need_since and covered_until >= (need_until - tol):
                sliced = df[(df["ts"] >= need_since) & (df["ts"] < need_until)]
                return sliced.reset_index(drop=True)
        except Exception as exc:
            log.warning("cache read failed for %s %s: %s — re-fetching",
                        symbol, timeframe, exc)

    df = _fetch_via_ccxt(symbol, timeframe, since_ms, until_ms)
    if not df.empty:
        try:
            df.to_parquet(cache, index=False)
        except Exception as exc:
            log.warning("cache write failed for %s %s: %s", symbol, timeframe, exc)
    return df
