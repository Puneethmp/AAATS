"""
Tests for markets/crypto/fetcher.py.

All external network calls are mocked — no live exchange or CoinGecko traffic.
Tests verify: OHLCV parsing, date filtering, timeframe validation,
backoff retry, and CoinGecko price/market-data helpers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from markets.crypto.fetcher import (
    fetch_coingecko_market_data,
    fetch_coingecko_ohlc,
    fetch_coingecko_price,
    fetch_ohlcv,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _raw_ohlcv(n: int = 5) -> list[list]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        ts = int((base.timestamp() + i * 86400) * 1000)
        rows.append([ts, 40000.0 + i, 41000.0 + i, 39000.0 + i, 40500.0 + i, 100.0 + i])
    return rows


# ── fetch_ohlcv tests ─────────────────────────────────────────────────────────

class TestFetchOHLCV:
    _start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    _end = datetime(2024, 1, 7, tzinfo=timezone.utc)

    def test_returns_correct_columns(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = _raw_ohlcv(5)

        with patch("markets.crypto.fetcher._build_exchange", return_value=mock_exchange):
            df = fetch_ohlcv("BTC/USDT", "1Day", self._start, self._end)

        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert len(df) == 5

    def test_timestamps_are_utc_aware(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = _raw_ohlcv(3)

        with patch("markets.crypto.fetcher._build_exchange", return_value=mock_exchange):
            df = fetch_ohlcv("BTC/USDT", "1Day", self._start, self._end)

        assert df["timestamp"].dt.tz is not None
        assert str(df["timestamp"].dt.tz) == "UTC"

    def test_rejects_unknown_timeframe(self):
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            fetch_ohlcv("BTC/USDT", "BADTF", self._start, self._end)

    def test_empty_response_returns_empty_df(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = []

        with patch("markets.crypto.fetcher._build_exchange", return_value=mock_exchange):
            df = fetch_ohlcv("BTC/USDT", "1Hour", self._start, self._end)

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_filters_rows_beyond_end(self):
        # All 5 rows are within a week; the last 2 would be beyond end if end is day 3
        end = datetime(2024, 1, 3, tzinfo=timezone.utc)
        mock_exchange = MagicMock()
        # First call returns 5 rows; second simulates pagination end
        mock_exchange.fetch_ohlcv.side_effect = [_raw_ohlcv(5), []]

        with patch("markets.crypto.fetcher._build_exchange", return_value=mock_exchange):
            df = fetch_ohlcv("BTC/USDT", "1Day", self._start, end)

        # Rows with timestamps after end should be filtered out
        end_ms = int(end.timestamp() * 1000)
        ts_ms = (df["timestamp"].astype("int64") // 1_000_000).tolist()
        assert all(t <= end_ms for t in ts_ms)

    def test_sorted_ascending_by_timestamp(self):
        # Return rows in reverse order to test sorting
        raw = list(reversed(_raw_ohlcv(5)))
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = raw

        with patch("markets.crypto.fetcher._build_exchange", return_value=mock_exchange):
            df = fetch_ohlcv("BTC/USDT", "1Day", self._start, self._end)

        assert df["timestamp"].is_monotonic_increasing

    def test_uses_custom_exchange(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.return_value = _raw_ohlcv(2)

        with patch("markets.crypto.fetcher._build_exchange", return_value=mock_exchange) as mock_builder:
            fetch_ohlcv("ETH/USDT", "1Hour", self._start, self._end, exchange_id="kraken")
            mock_builder.assert_called_once_with("kraken")

    def test_retries_on_failure_then_succeeds(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.side_effect = [
            Exception("timeout"),
            _raw_ohlcv(3),
        ]

        with patch("markets.crypto.fetcher._build_exchange", return_value=mock_exchange):
            with patch("markets.crypto.fetcher.time.sleep"):
                df = fetch_ohlcv("BTC/USDT", "1Day", self._start, self._end)

        assert len(df) == 3

    def test_raises_after_all_retries_exhausted(self):
        mock_exchange = MagicMock()
        mock_exchange.fetch_ohlcv.side_effect = Exception("network down")

        with patch("markets.crypto.fetcher._build_exchange", return_value=mock_exchange):
            with patch("markets.crypto.fetcher.time.sleep"):
                with pytest.raises(Exception, match="network down"):
                    fetch_ohlcv("BTC/USDT", "1Day", self._start, self._end)


# ── fetch_coingecko_ohlc tests ────────────────────────────────────────────────

class TestFetchCoinGeckoOHLC:
    _ohlc_response = [
        [1704067200000, 42000.0, 43000.0, 41500.0, 42500.0],
        [1704153600000, 42500.0, 44000.0, 42000.0, 43500.0],
    ]

    def test_returns_correct_columns(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._ohlc_response
        mock_resp.raise_for_status = MagicMock()

        with patch("markets.crypto.fetcher.requests.get", return_value=mock_resp):
            df = fetch_coingecko_ohlc("bitcoin", days=7)

        assert list(df.columns) == ["timestamp", "open", "high", "low", "close"]

    def test_timestamps_are_utc(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._ohlc_response
        mock_resp.raise_for_status = MagicMock()

        with patch("markets.crypto.fetcher.requests.get", return_value=mock_resp):
            df = fetch_coingecko_ohlc("bitcoin", days=7)

        assert df["timestamp"].dt.tz is not None

    def test_empty_response_returns_empty_df(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("markets.crypto.fetcher.requests.get", return_value=mock_resp):
            df = fetch_coingecko_ohlc("bitcoin", days=7)

        assert df.empty

    def test_http_error_triggers_retry(self):
        mock_bad = MagicMock()
        mock_bad.raise_for_status.side_effect = requests.HTTPError("429")
        mock_good = MagicMock()
        mock_good.json.return_value = self._ohlc_response
        mock_good.raise_for_status = MagicMock()

        with patch("markets.crypto.fetcher.requests.get", side_effect=[mock_bad, mock_good]):
            with patch("markets.crypto.fetcher.time.sleep"):
                df = fetch_coingecko_ohlc("bitcoin", days=7)

        assert len(df) == 2


# ── fetch_coingecko_price tests ───────────────────────────────────────────────

class TestFetchCoinGeckoPrice:
    def test_returns_price_dict(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"bitcoin": {"usd": 65000.0}}
        mock_resp.raise_for_status = MagicMock()

        with patch("markets.crypto.fetcher.requests.get", return_value=mock_resp):
            result = fetch_coingecko_price(["bitcoin"])

        assert result["bitcoin"]["usd"] == 65000.0

    def test_multiple_coins(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "bitcoin": {"usd": 65000.0},
            "ethereum": {"usd": 3500.0},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("markets.crypto.fetcher.requests.get", return_value=mock_resp):
            result = fetch_coingecko_price(["bitcoin", "ethereum"])

        assert "bitcoin" in result
        assert "ethereum" in result


# ── fetch_coingecko_market_data tests ─────────────────────────────────────────

class TestFetchCoinGeckoMarketData:
    _market_response = [
        {
            "id": "bitcoin",
            "symbol": "btc",
            "market_cap": 1_300_000_000_000,
            "total_volume": 30_000_000_000,
            "current_price": 65000.0,
            "market_cap_rank": 1,
        }
    ]

    def test_returns_market_data_dict(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._market_response
        mock_resp.raise_for_status = MagicMock()

        with patch("markets.crypto.fetcher.requests.get", return_value=mock_resp):
            result = fetch_coingecko_market_data("bitcoin")

        assert result["id"] == "bitcoin"
        assert result["market_cap_rank"] == 1

    def test_empty_response_returns_empty_dict(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("markets.crypto.fetcher.requests.get", return_value=mock_resp):
            result = fetch_coingecko_market_data("unknown-coin")

        assert result == {}
