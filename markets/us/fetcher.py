"""
US market data fetcher using Alpaca Markets (alpaca-py SDK).
Handles historical OHLCV bars and live WebSocket streaming with exponential backoff.
Halts the US market module after 6 consecutive failures.
"""

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config.settings import USConfig
from foundation.audit_trail import AuditTrail
from foundation.kill_switch import halt
from foundation.logger import get_logger

_log = get_logger("us", "fetcher")

_BACKOFF_DELAYS: list[int] = [1, 2, 4, 8, 16]  # 5 waits → 6 total attempts

_TIMEFRAME_MAP: dict[str, TimeFrame] = {
    "1Day": TimeFrame.Day,
    "1Hour": TimeFrame.Hour,
    "1Min": TimeFrame.Minute,
}


def _with_backoff(
    fn: Callable[[], Any],
    audit: AuditTrail,
    context: dict[str, Any],
) -> Any:
    """
    Execute fn() with exponential backoff on failure.
    Each failure is logged to the audit trail as a REJECTION.
    Calls halt(market="us") and re-raises after 6 consecutive failures.

    Args:
        fn:      Zero-argument callable to attempt.
        audit:   AuditTrail for logging each failure.
        context: Extra fields included in every audit entry.

    Returns:
        The return value of fn() on first success.
    """
    for attempt, delay in enumerate(_BACKOFF_DELAYS, start=1):
        try:
            return fn()
        except Exception as exc:
            _log.warning(f"Attempt {attempt}/6 failed: {exc}")
            audit.append(
                market="us",
                module="fetcher",
                event_type="REJECTION",
                details={**context, "attempt": attempt, "error": str(exc)},
                result="REJECTED",
                reason=f"Alpaca fetch failed (attempt {attempt}): {exc}",
            )
            time.sleep(delay)

    # 6th and final attempt
    try:
        return fn()
    except Exception as exc:
        _log.error("All 6 attempts exhausted — halting US market.")
        audit.append(
            market="us",
            module="fetcher",
            event_type="REJECTION",
            details={**context, "attempt": 6, "error": str(exc)},
            result="REJECTED",
            reason=f"Alpaca fetch failed (attempt 6): {exc}",
        )
        halt(market="us", reason="Alpaca fetch failed 6x", triggered_by="fetcher")
        raise


def fetch_historical(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: str,
    config: USConfig,
) -> pd.DataFrame:
    """
    Fetch historical OHLCV bars for a US equity symbol from Alpaca Markets.

    Args:
        symbol:    Ticker symbol (e.g. "AAPL").
        start:     Start datetime (UTC-aware recommended).
        end:       End datetime (UTC-aware recommended).
        timeframe: Bar size — "1Day", "1Hour", or "1Min".
        config:    USConfig carrying Alpaca API credentials.

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].
        Timestamps are UTC-aware. Empty DataFrame if Alpaca returns no data.

    Raises:
        ValueError: If timeframe is not a recognised value.
        Exception:  After 6 consecutive Alpaca failures (halt is also triggered).
    """
    if timeframe not in _TIMEFRAME_MAP:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. Valid values: {list(_TIMEFRAME_MAP)}"
        )

    tf = _TIMEFRAME_MAP[timeframe]
    audit = AuditTrail()
    context: dict[str, Any] = {"symbol": symbol, "timeframe": timeframe}

    def _fetch() -> pd.DataFrame:
        client = StockHistoricalDataClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
        )
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            start=start,
            end=end,
            timeframe=tf,
        )
        bars = client.get_stock_bars(request)
        raw_df = bars.df

        if raw_df.empty:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        # alpaca-py returns MultiIndex (symbol, timestamp) for historical data
        if isinstance(raw_df.index, pd.MultiIndex):
            raw_df = raw_df.xs(symbol, level="symbol")

        df = raw_df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index, utc=True)
        df.index.name = "timestamp"
        return df.reset_index()

    _log.info(f"Fetching {timeframe} bars for {symbol}")
    return _with_backoff(_fetch, audit, context)


def stream_live(
    symbols: list[str],
    callback: Callable[[str, pd.Series], None],
    config: USConfig,
) -> None:
    """
    Subscribe to live bar updates for US equity symbols via Alpaca WebSocket.
    Calls callback(symbol, bar) on each incoming bar.
    Reconnects with exponential backoff on disconnect.

    Args:
        symbols:  Ticker symbols to subscribe to (e.g. ["AAPL", "TSLA"]).
        callback: Called as callback(symbol, bar_series) on each incoming bar.
                  bar_series has keys: timestamp, open, high, low, close, volume.
        config:   USConfig carrying Alpaca API credentials.
    """
    audit = AuditTrail()
    context: dict[str, Any] = {"symbols": symbols, "action": "stream_live"}

    async def _bar_handler(bar) -> None:
        series = pd.Series(
            {
                "timestamp": pd.to_datetime(bar.timestamp, utc=True),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )
        callback(bar.symbol, series)

    def _connect() -> None:
        stream = StockDataStream(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
        )
        stream.subscribe_bars(_bar_handler, *symbols)
        stream.run()

    _log.info(f"Starting live stream for {symbols}")
    _with_backoff(_connect, audit, context)
