"""
India F&O data fetcher via Angel One SmartAPI.
Fetches NSE option chain data (OI, IV, strike data) and OHLCV for F&O instruments.

SmartConnect client is injected for testability (dependency injection).
Production: pass authenticated SmartConnect(api_key) instance.
Tests: pass MagicMock().
"""

import concurrent.futures
import re
import time
from typing import Any

import pandas as pd
import pytz

from foundation.audit_trail import AuditTrail
from foundation.kill_switch import halt
from foundation.logger import get_logger

_log = get_logger("india", "fo_fetcher")
_IST = pytz.timezone("Asia/Kolkata")

_BACKOFF_DELAYS: list[int] = [1, 2, 4, 8, 16]  # 5 waits → 6 total attempts
_TIMEOUT_SECONDS: int = 30

_OPTION_CHAIN_COLUMNS: list[str] = [
    "strike",
    "option_type",
    "ltp",
    "oi",
    "change_in_oi",
    "iv",
    "bid",
    "ask",
    "volume",
]
_OHLCV_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]

# Extract strike price and option type from symbols like "NIFTY25MAY24000CE"
_SYMBOL_PATTERN = re.compile(r"(\d+)(CE|PE)$")


def _with_backoff(
    fn,
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
                module="fo_fetcher",
                event_type="REJECTION",
                details={**context, "attempt": attempt, "error": str(exc)},
                result="REJECTED",
                reason=f"Angel One F&O fetch failed (attempt {attempt}): {exc}",
            )
            time.sleep(delay)

    # 6th and final attempt
    try:
        return fn()
    except Exception as exc:
        _log.error("All 6 attempts exhausted — halting India market.")
        audit.append(
            market="india",
            module="fo_fetcher",
            event_type="REJECTION",
            details={**context, "attempt": 6, "error": str(exc)},
            result="REJECTED",
            reason=f"Angel One F&O fetch failed (attempt 6): {exc}",
        )
        halt(
            market="india",
            reason="Angel One F&O fetch failed 6x",
            triggered_by="fo_fetcher",
        )
        raise


def _api_call_with_timeout(fn, timeout: int = _TIMEOUT_SECONDS) -> Any:
    """Run fn() in a thread and raise TimeoutError if it does not complete within timeout seconds."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Angel One API call timed out after {timeout}s")


def _parse_option_type(symbol: str) -> str:
    """Extract CE or PE from a trading symbol string."""
    match = _SYMBOL_PATTERN.search(symbol)
    return match.group(2) if match else "UNKNOWN"


def _parse_strike(symbol: str) -> float:
    """Extract strike price from a trading symbol string, returns NaN if not found."""
    match = _SYMBOL_PATTERN.search(symbol)
    return float(match.group(1)) if match else float("nan")


def fetch_option_chain(
    underlying: str,
    expiry: str,
    smart_client,
    config,
) -> pd.DataFrame:
    """
    Fetch NSE F&O option chain data for the given underlying and expiry.

    Calls Angel One getMarketData with mode="FULL" on NFO tokens for the chain.
    Rows where IV <= 0 are filtered and audit-logged — illiquid/invalid strikes
    cannot be priced and must not enter the strategy layer.

    Args:
        underlying:   Underlying index or stock symbol, e.g. "NIFTY".
        expiry:       Expiry date in "DDMMMYYYY" format, e.g. "29MAY2025".
        smart_client: Authenticated SmartConnect client (injected).
        config:       Settings object.

    Returns:
        DataFrame with columns [strike, option_type, ltp, oi, change_in_oi, iv, bid, ask, volume].
        Empty DataFrame (same columns) if API returns no valid data.

    Raises:
        Exception: After 6 consecutive API failures (India halt also triggered).
    """
    audit = AuditTrail()
    context: dict[str, Any] = {
        "underlying": underlying,
        "expiry": expiry,
        "action": "fetch_option_chain",
    }

    def _fetch() -> pd.DataFrame:
        params = {
            "mode": "FULL",
            "exchangeTokens": {
                "NFO": []
            },  # populated from instrument file in production
            "underlying": underlying,
            "expiry": expiry,
        }
        response = _api_call_with_timeout(lambda: smart_client.getMarketData(params))

        if not response or not response.get("status"):
            msg = (
                response.get("message", "Unknown error")
                if isinstance(response, dict)
                else "Empty or malformed response"
            )
            raise RuntimeError(f"getMarketData returned failure: {msg}")

        fetched = (response.get("data") or {}).get("fetched") or []
        if not fetched:
            return pd.DataFrame(columns=_OPTION_CHAIN_COLUMNS)

        rows = []
        for item in fetched:
            symbol = item.get("tradingSymbol", "")
            option_type = _parse_option_type(symbol)
            strike = item.get("strikePrice") or _parse_strike(symbol)
            iv = float(item.get("impliedVolatility") or 0.0)

            if iv <= 0:
                _log.debug(f"Skipping {symbol}: IV={iv} (invalid/illiquid)")
                audit.append(
                    market="india",
                    module="fo_fetcher",
                    event_type="REJECTION",
                    details={**context, "symbol": symbol, "iv": iv},
                    result="REJECTED",
                    reason=f"Option {symbol} has IV <= 0 — illiquid/invalid strike skipped",
                )
                continue

            best_five = item.get("bestFiveData") or []
            bid = float(best_five[0].get("buyPrice", 0.0)) if best_five else 0.0
            ask = float(best_five[0].get("sellPrice", 0.0)) if best_five else 0.0

            rows.append(
                {
                    "strike": float(strike),
                    "option_type": option_type,
                    "ltp": float(item.get("ltp") or 0.0),
                    "oi": float(item.get("opnInterest") or 0.0),
                    "change_in_oi": float(item.get("netChangeInOI") or 0.0),
                    "iv": iv,
                    "bid": bid,
                    "ask": ask,
                    "volume": float(item.get("volume") or 0.0),
                }
            )

        if not rows:
            return pd.DataFrame(columns=_OPTION_CHAIN_COLUMNS)
        return pd.DataFrame(rows, columns=_OPTION_CHAIN_COLUMNS)

    _log.info(f"Fetching option chain for {underlying} expiry {expiry}")
    return _with_backoff(_fetch, audit, context)


def fetch_fo_ohlcv(
    symbol: str,
    token: str,
    interval: str,
    from_date: str,
    to_date: str,
    smart_client,
    config,
) -> pd.DataFrame:
    """
    Fetch OHLCV historical data for a futures or options instrument.

    Uses the same getCandleData endpoint as the equity fetcher but with
    exchange="NFO". Timestamps are converted from IST to UTC.

    Args:
        symbol:       F&O trading symbol, e.g. "NIFTY25MAY24000CE".
        token:        Angel One instrument token for this F&O contract.
        interval:     Candle interval — "ONE_DAY", "ONE_HOUR", "FIFTEEN_MINUTE", etc.
        from_date:    Range start "YYYY-MM-DD HH:MM".
        to_date:      Range end "YYYY-MM-DD HH:MM".
        smart_client: Authenticated SmartConnect client (injected).
        config:       Settings object.

    Returns:
        DataFrame with columns [timestamp, open, high, low, close, volume].
        Timestamps are UTC-aware. Empty DataFrame (same columns) if no data.

    Raises:
        Exception: After 6 consecutive API failures (India halt also triggered).
    """
    audit = AuditTrail()
    context: dict[str, Any] = {
        "symbol": symbol,
        "token": token,
        "interval": interval,
        "action": "fetch_fo_ohlcv",
    }

    def _fetch() -> pd.DataFrame:
        params = {
            "exchange": "NFO",
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

    _log.info(f"Fetching {interval} F&O bars for {symbol} (NFO:{token})")
    return _with_backoff(_fetch, audit, context)
