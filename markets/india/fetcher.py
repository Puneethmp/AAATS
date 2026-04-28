"""
India market data fetcher via Angel One SmartAPI.
Fetches NSE/BSE OHLCV historical bars and live tick data with exponential backoff.

SmartConnect client is injected for testability (dependency injection).
Production: pass authenticated SmartConnect(api_key) instance.
Tests: pass MagicMock().
"""

import concurrent.futures
import time
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytz

from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from foundation.audit_trail import AuditTrail
from foundation.kill_switch import halt
from foundation.logger import get_logger

_log = get_logger("india", "fetcher")
_IST = pytz.timezone("Asia/Kolkata")

_BACKOFF_DELAYS: list[int] = [1, 2, 4, 8, 16]  # 5 waits → 6 total attempts
_TIMEOUT_SECONDS: int = 30
_OHLCV_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]

# Angel One exchange type codes for SmartWebSocketV2 subscription
_EXCHANGE_TYPE_MAP: dict[str, int] = {
    "NSE": 1,
    "NFO": 2,
    "BSE": 3,
    "MCX": 5,
}


def _with_backoff(
    fn: Callable[[], Any],
    audit: AuditTrail,
    context: dict[str, Any],
) -> Any:
    """
    Execute fn() with exponential backoff on failure.
    Each failure appends a REJECTION entry to the audit trail.
    Calls halt(market='india') and re-raises after 6 consecutive failures.
    """
    for attempt, delay in enumerate(_BACKOFF_DELAYS, start=1):
        try:
            return fn()
        except Exception as exc:
            _log.warning(f"Attempt {attempt}/6 failed: {exc}")
            audit.append(
                market="india",
                module="fetcher",
                event_type="REJECTION",
                details={**context, "attempt": attempt, "error": str(exc)},
                result="REJECTED",
                reason=f"Angel One fetch failed (attempt {attempt}): {exc}",
            )
            time.sleep(delay)

    # 6th and final attempt
    try:
        return fn()
    except Exception as exc:
        _log.error("All 6 attempts exhausted — halting India market.")
        audit.append(
            market="india",
            module="fetcher",
            event_type="REJECTION",
            details={**context, "attempt": 6, "error": str(exc)},
            result="REJECTED",
            reason=f"Angel One fetch failed (attempt 6): {exc}",
        )
        halt(market="india", reason="Angel One fetch failed 6x", triggered_by="fetcher")
        raise


def _api_call_with_timeout(
    fn: Callable[[], Any], timeout: int = _TIMEOUT_SECONDS
) -> Any:
    """Run fn() in a thread and raise TimeoutError if it does not complete within timeout seconds."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Angel One API call timed out after {timeout}s")


def fetch_historical(
    symbol: str,
    token: str,
    exchange: str,
    interval: str,
    from_date: str,
    to_date: str,
    smart_client,
    config,
) -> pd.DataFrame:
    """
    Fetch NSE/BSE OHLCV historical bars from Angel One getCandleData endpoint.

    Timestamps from Angel One are IST; they are converted to UTC before returning.

    Args:
        symbol:       Display symbol for logging (e.g. "SBIN").
        token:        Angel One instrument token (e.g. "3045").
        exchange:     "NSE" or "BSE".
        interval:     Candle interval — "ONE_DAY", "ONE_HOUR", "FIFTEEN_MINUTE", etc.
        from_date:    Range start "YYYY-MM-DD HH:MM".
        to_date:      Range end "YYYY-MM-DD HH:MM".
        smart_client: Authenticated SmartConnect client (injected).
        config:       Settings object (unused here; available for future auth refresh).

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].
        Timestamps are UTC-aware. Empty DataFrame if API returns no data.

    Raises:
        Exception: After 6 consecutive API failures (India halt is also triggered).
    """
    audit = AuditTrail()
    context: dict[str, Any] = {
        "symbol": symbol,
        "token": token,
        "exchange": exchange,
        "interval": interval,
    }

    def _fetch() -> pd.DataFrame:
        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        }
        response = _api_call_with_timeout(lambda: smart_client.getCandleData(params))

        if not response or not response.get("status"):
            msg = (
                response.get("message", "Unknown error")
                if isinstance(response, dict)
                else "Empty or malformed response"
            )
            raise RuntimeError(f"getCandleData returned failure: {msg}")

        raw_data = response.get("data") or []
        if not raw_data:
            return pd.DataFrame(columns=_OHLCV_COLUMNS)

        rows = []
        for bar in raw_data:
            ts_raw = pd.to_datetime(bar[0])
            if ts_raw.tzinfo is None:
                ts_raw = _IST.localize(ts_raw)
            ts_utc = ts_raw.tz_convert(pytz.utc)
            rows.append(
                {
                    "timestamp": ts_utc,
                    "open": float(bar[1]),
                    "high": float(bar[2]),
                    "low": float(bar[3]),
                    "close": float(bar[4]),
                    "volume": float(bar[5]),
                }
            )

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    _log.info(f"Fetching {interval} bars for {symbol} ({exchange}:{token})")
    return _with_backoff(_fetch, audit, context)


def stream_live(
    token_list: list[dict],
    callback: Callable[[str, dict], None],
    smart_client,
    config,
) -> None:
    """
    Stream live tick data from Angel One SmartAPI WebSocket V2.
    Calls callback(token, bar_dict) on each incoming tick.
    Reconnects with exponential backoff on connection failure.

    Args:
        token_list:   [{"exchange": "NSE", "token": "3045"}, ...]
        callback:     Called as callback(token, bar_dict).
                      bar_dict keys: token, exchange, ltp, timestamp.
        smart_client: Authenticated SmartConnect client (kept for interface symmetry).
        config:       Settings with india.angel_auth_token / api_key / client_id / feed_token.
    """
    audit = AuditTrail()
    context: dict[str, Any] = {
        "token_count": len(token_list),
        "action": "stream_live",
    }

    # Build SmartWebSocketV2 subscription payload and reverse lookup map
    exchange_tokens: dict[int, list[str]] = {}
    token_exchange_map: dict[str, str] = {}
    for item in token_list:
        ex = item["exchange"]
        tok = item["token"]
        ex_type = _EXCHANGE_TYPE_MAP.get(ex, 1)
        exchange_tokens.setdefault(ex_type, []).append(tok)
        token_exchange_map[tok] = ex

    sub_list = [
        {"exchangeType": ex_type, "tokens": tokens}
        for ex_type, tokens in exchange_tokens.items()
    ]

    def _connect() -> None:
        sws = SmartWebSocketV2(
            auth_token=config.india.angel_auth_token,
            api_key=config.india.angel_api_key,
            client_code=config.india.angel_client_id,
            feed_token=config.india.angel_feed_token,
        )

        def _on_data(wsapp, message):
            try:
                tok = str(message.get("token", ""))
                bar = {
                    "token": tok,
                    "exchange": token_exchange_map.get(tok, ""),
                    "ltp": float(message.get("last_traded_price", 0)) / 100.0,
                    "timestamp": pd.Timestamp.now(tz="UTC"),
                }
                callback(tok, bar)
            except Exception as exc:
                _log.warning(f"Tick processing error: {exc}")

        def _on_open(wsapp):
            sws.subscribe("AAATS_STREAM", 1, sub_list)

        def _on_close(wsapp):
            _log.warning("WebSocket connection closed.")

        def _on_error(*args):
            _log.error(f"WebSocket error: {args}")

        sws.on_data = _on_data
        sws.on_open = _on_open
        sws.on_close = _on_close
        sws.on_error = _on_error
        sws.connect()

    _log.info(f"Starting live stream for {len(token_list)} token(s).")
    _with_backoff(_connect, audit, context)
