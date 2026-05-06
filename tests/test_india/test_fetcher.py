"""
Tests for markets/india/fetcher.py.
All Angel One API calls are mocked — zero real network calls.
"""

from unittest.mock import ANY, MagicMock, call, patch

import pytest

from markets.india.fetcher import fetch_historical, stream_live

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.india.angel_auth_token = "test_jwt"
    cfg.india.angel_api_key = "test_api_key"
    cfg.india.angel_client_id = "TEST_CLIENT"
    cfg.india.angel_feed_token = "test_feed_token"
    return cfg


@pytest.fixture
def sample_candle_response():
    """Three IST-timestamped bars as returned by Angel One getCandleData."""
    return {
        "status": True,
        "message": "SUCCESS",
        "data": [
            ["2025-01-02T09:15:00+05:30", 500.0, 510.0, 495.0, 505.0, 10000],
            ["2025-01-03T09:15:00+05:30", 505.0, 520.0, 500.0, 515.0, 12000],
            ["2025-01-06T09:15:00+05:30", 515.0, 530.0, 510.0, 525.0, 11000],
        ],
    }


@pytest.fixture
def mock_smart_client(sample_candle_response):
    client = MagicMock()
    client.getCandleData.return_value = sample_candle_response
    return client


def _call_fetch(smart_client, mock_config):
    """Helper: calls fetch_historical with standard test arguments."""
    return fetch_historical(
        symbol="SBIN",
        token="3045",
        exchange="NSE",
        interval="ONE_DAY",
        from_date="2025-01-02 09:15",
        to_date="2025-01-06 15:30",
        smart_client=smart_client,
        config=mock_config,
    )


# ── fetch_historical tests ─────────────────────────────────────────────────────


class TestFetchHistorical:
    def test_returns_correct_columns(self, mock_smart_client, mock_config):
        """Returns DataFrame with exactly the expected OHLCV columns and correct row count."""
        with patch("markets.india.fetcher.AuditTrail"):
            df = _call_fetch(mock_smart_client, mock_config)

        assert list(df.columns) == [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
        assert len(df) == 3

    def test_backoff_retries_then_succeeds(self, mock_config, sample_candle_response):
        """getCandleData fails 3 times then succeeds; time.sleep called with correct backoff delays."""
        smart_client = MagicMock()
        smart_client.getCandleData.side_effect = [
            ConnectionError("timeout"),
            ConnectionError("timeout"),
            ConnectionError("timeout"),
            sample_candle_response,
        ]

        with (
            patch("markets.india.fetcher.AuditTrail"),
            patch("markets.india.fetcher.time.sleep") as mock_sleep,
        ):
            df = _call_fetch(smart_client, mock_config)

        assert len(df) == 3
        assert mock_sleep.call_count == 3
        assert mock_sleep.call_args_list == [call(1), call(2), call(4)]

    def test_kill_switch_halt_on_6th_failure(self, mock_config):
        """halt(market='india') is called when getCandleData fails all 6 attempts."""
        smart_client = MagicMock()
        smart_client.getCandleData.side_effect = ConnectionError("server down")

        with (
            patch("markets.india.fetcher.AuditTrail"),
            patch("markets.india.fetcher.time.sleep"),
            patch("markets.india.fetcher.halt") as mock_halt,
        ):
            with pytest.raises(ConnectionError):
                _call_fetch(smart_client, mock_config)

        mock_halt.assert_called_once_with(
            market="india",
            reason=ANY,
            triggered_by="fetcher",
        )

    def test_audit_trail_rejection_on_failure(
        self, mock_config, sample_candle_response
    ):
        """AuditTrail.append is called with event_type='REJECTION' on each failure."""
        smart_client = MagicMock()
        smart_client.getCandleData.side_effect = [
            RuntimeError("API error"),
            sample_candle_response,
        ]
        mock_audit = MagicMock()

        with (
            patch("markets.india.fetcher.AuditTrail", return_value=mock_audit),
            patch("markets.india.fetcher.time.sleep"),
        ):
            _call_fetch(smart_client, mock_config)

        mock_audit.append.assert_called_once()
        call_kwargs = mock_audit.append.call_args[1]
        assert call_kwargs["event_type"] == "REJECTION"

    def test_timestamps_stored_as_utc(self, mock_smart_client, mock_config):
        """Timestamps from Angel One (IST = UTC+5:30) are converted to UTC before returning."""
        with patch("markets.india.fetcher.AuditTrail"):
            df = _call_fetch(mock_smart_client, mock_config)

        # pandas 3 normalises to datetime.timezone.utc; check UTC by offset and values
        assert df["timestamp"].dt.tz is not None
        assert str(df["timestamp"].dt.tz) == "UTC"
        # 09:15 IST = 03:45 UTC
        assert df.iloc[0]["timestamp"].hour == 3
        assert df.iloc[0]["timestamp"].minute == 45

    def test_empty_data_returns_empty_dataframe(self, mock_config):
        """API success with empty data list returns empty DataFrame with correct columns."""
        smart_client = MagicMock()
        smart_client.getCandleData.return_value = {
            "status": True,
            "message": "SUCCESS",
            "data": [],
        }
        with patch("markets.india.fetcher.AuditTrail"):
            df = _call_fetch(smart_client, mock_config)

        assert df.empty
        assert list(df.columns) == [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]


# ── stream_live tests ──────────────────────────────────────────────────────────


class TestStreamLive:
    def test_callback_called_with_correct_data_shape(self, mock_config):
        """Callback receives (token, bar_dict) with all expected keys and correct ltp."""
        callback = MagicMock()
        token_list = [{"exchange": "NSE", "token": "3045"}]
        mock_sws = MagicMock()

        def fake_connect():
            # Simulate on_open (triggers subscribe) then one tick arriving via on_data
            mock_sws.on_open(None)
            mock_sws.on_data(None, {"token": "3045", "last_traded_price": 50500})

        mock_sws.connect.side_effect = fake_connect

        with (
            patch("markets.india.fetcher.AuditTrail"),
            patch("markets.india.fetcher.SmartWebSocketV2", return_value=mock_sws),
        ):
            stream_live(token_list, callback, MagicMock(), mock_config)

        callback.assert_called_once()
        tok_arg, bar_arg = callback.call_args[0]
        assert tok_arg == "3045"
        assert set(bar_arg.keys()) == {"token", "exchange", "ltp", "timestamp"}
        assert bar_arg["ltp"] == pytest.approx(505.0)  # 50500 paise → 505.00 rupees
        assert bar_arg["exchange"] == "NSE"
        assert bar_arg["timestamp"].tzinfo is not None  # UTC-aware
