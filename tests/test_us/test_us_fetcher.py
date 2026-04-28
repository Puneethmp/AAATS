"""
Tests for markets/us/fetcher.py.
All tests mock Alpaca SDK — no real API calls are made.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from config.settings import USConfig

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_us_config() -> USConfig:
    return USConfig(alpaca_api_key="test_key", alpaca_secret_key="test_secret")


def _make_multiindex_df(symbol: str = "AAPL", rows: int = 3) -> pd.DataFrame:
    """Build a MultiIndex DataFrame matching alpaca-py's historical response format."""
    timestamps = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    index = pd.MultiIndex.from_tuples(
        [(symbol, ts) for ts in timestamps],
        names=["symbol", "timestamp"],
    )
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "high": [105.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [103.0 + i for i in range(rows)],
            "volume": [1000.0 + i * 100 for i in range(rows)],
        },
        index=index,
    )


def _make_mock_bars(symbol: str = "AAPL", rows: int = 3) -> MagicMock:
    """Return a mock bars response whose .df is a valid MultiIndex DataFrame."""
    mock_bars = MagicMock()
    mock_bars.df = _make_multiindex_df(symbol, rows)
    return mock_bars


# ── fetch_historical tests ────────────────────────────────────────────────────


class TestFetchHistorical:
    def test_returns_correct_columns(self, tmp_path):
        """Successful fetch returns DataFrame with exactly the expected columns."""
        config = _make_us_config()
        mock_client = MagicMock()
        mock_client.get_stock_bars.return_value = _make_mock_bars("AAPL", 3)

        with (
            patch(
                "markets.us.fetcher.StockHistoricalDataClient", return_value=mock_client
            ),
            patch("markets.us.fetcher.AuditTrail") as MockAudit,
            patch("markets.us.fetcher.time.sleep"),
        ):
            MockAudit.return_value = MagicMock()
            from markets.us.fetcher import fetch_historical

            df = fetch_historical(
                symbol="AAPL",
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 1, 4, tzinfo=timezone.utc),
                timeframe="1Day",
                config=config,
            )

        assert list(df.columns) == [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
        assert len(df) == 3
        assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])

    def test_backoff_retries_3x_then_succeeds(self, tmp_path):
        """Fetch retries on failure and succeeds on the 4th attempt."""
        config = _make_us_config()
        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = [
            Exception("network error 1"),
            Exception("network error 2"),
            Exception("network error 3"),
            _make_mock_bars("AAPL", 2),
        ]

        mock_audit = MagicMock()
        sleep_calls = []

        with (
            patch(
                "markets.us.fetcher.StockHistoricalDataClient", return_value=mock_client
            ),
            patch("markets.us.fetcher.AuditTrail", return_value=mock_audit),
            patch(
                "markets.us.fetcher.time.sleep",
                side_effect=lambda s: sleep_calls.append(s),
            ),
            patch("markets.us.fetcher.halt"),
        ):
            from markets.us.fetcher import fetch_historical

            df = fetch_historical(
                symbol="AAPL",
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 1, 3, tzinfo=timezone.utc),
                timeframe="1Day",
                config=config,
            )

        assert len(df) == 2
        assert sleep_calls == [1, 2, 4]
        assert mock_audit.append.call_count == 3
        rejection_results = [
            c.kwargs["result"] for c in mock_audit.append.call_args_list
        ]
        assert all(r == "REJECTED" for r in rejection_results)

    def test_halt_called_on_6th_failure(self, tmp_path):
        """halt(market='us') is called when all 6 attempts fail."""
        config = _make_us_config()
        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = Exception("persistent error")

        with (
            patch(
                "markets.us.fetcher.StockHistoricalDataClient", return_value=mock_client
            ),
            patch("markets.us.fetcher.AuditTrail", return_value=MagicMock()),
            patch("markets.us.fetcher.time.sleep"),
            patch("markets.us.fetcher.halt") as mock_halt,
        ):
            from markets.us.fetcher import fetch_historical

            with pytest.raises(Exception, match="persistent error"):
                fetch_historical(
                    symbol="AAPL",
                    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    end=datetime(2024, 1, 7, tzinfo=timezone.utc),
                    timeframe="1Day",
                    config=config,
                )

        mock_halt.assert_called_once_with(
            market="us",
            reason="Alpaca fetch failed 6x",
            triggered_by="fetcher",
        )

    def test_audit_rejection_on_failure(self, tmp_path):
        """Each failed attempt appends a REJECTION entry to the audit trail."""
        config = _make_us_config()
        mock_client = MagicMock()
        mock_client.get_stock_bars.side_effect = [
            Exception("timeout"),
            _make_mock_bars("TSLA", 1),
        ]
        mock_audit = MagicMock()

        with (
            patch(
                "markets.us.fetcher.StockHistoricalDataClient", return_value=mock_client
            ),
            patch("markets.us.fetcher.AuditTrail", return_value=mock_audit),
            patch("markets.us.fetcher.time.sleep"),
            patch("markets.us.fetcher.halt"),
        ):
            from markets.us.fetcher import fetch_historical

            fetch_historical(
                symbol="TSLA",
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 1, 2, tzinfo=timezone.utc),
                timeframe="1Day",
                config=config,
            )

        assert mock_audit.append.call_count == 1
        kwargs = mock_audit.append.call_args.kwargs
        assert kwargs["event_type"] == "REJECTION"
        assert kwargs["result"] == "REJECTED"
        assert kwargs["market"] == "us"

    def test_invalid_timeframe_raises_value_error(self):
        """fetch_historical raises ValueError for unknown timeframe strings."""
        from markets.us.fetcher import fetch_historical

        config = _make_us_config()
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            fetch_historical(
                symbol="AAPL",
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 1, 2, tzinfo=timezone.utc),
                timeframe="5Min",
                config=config,
            )


# ── stream_live tests ─────────────────────────────────────────────────────────


class TestStreamLive:
    def test_stream_callback_called(self):
        """stream_live registers a bar handler; invoking it calls the user callback."""
        config = _make_us_config()
        received: list[tuple] = []

        def user_callback(sym: str, bar: pd.Series) -> None:
            received.append((sym, bar))

        captured_handlers: list = []
        mock_stream = MagicMock()

        def fake_subscribe(handler, *syms):
            captured_handlers.append(handler)

        mock_stream.subscribe_bars.side_effect = fake_subscribe
        mock_stream.run.return_value = None

        with (
            patch("markets.us.fetcher.StockDataStream", return_value=mock_stream),
            patch("markets.us.fetcher.AuditTrail", return_value=MagicMock()),
            patch("markets.us.fetcher.time.sleep"),
        ):
            from markets.us.fetcher import stream_live

            stream_live(["AAPL"], user_callback, config)

        assert mock_stream.subscribe_bars.called
        assert mock_stream.run.called
        assert len(captured_handlers) == 1

        # Simulate a bar arriving by invoking the captured async handler
        class MockBar:
            symbol = "AAPL"
            timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
            open = 100.0
            high = 105.0
            low = 99.0
            close = 103.0
            volume = 1000.0

        asyncio.run(captured_handlers[0](MockBar()))

        assert len(received) == 1
        sym, bar = received[0]
        assert sym == "AAPL"
        assert bar["close"] == 103.0
        assert bar["volume"] == 1000.0
        assert isinstance(bar["timestamp"], pd.Timestamp)
