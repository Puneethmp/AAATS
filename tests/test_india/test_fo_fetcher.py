"""
Tests for markets/india/fo_fetcher.py.
All Angel One API calls are mocked — zero real network calls.
"""

from unittest.mock import ANY, MagicMock, patch

import pytest

from markets.india.fo_fetcher import fetch_fo_ohlcv, fetch_option_chain

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    return MagicMock()


@pytest.fixture
def sample_option_chain_response():
    """Two CE and two PE strikes with valid IV as returned by Angel One getMarketData."""
    return {
        "status": True,
        "message": "SUCCESS",
        "data": {
            "fetched": [
                {
                    "tradingSymbol": "NIFTY25MAY24000CE",
                    "strikePrice": 24000.0,
                    "ltp": 150.0,
                    "opnInterest": 50000.0,
                    "netChangeInOI": 2000.0,
                    "impliedVolatility": 18.5,
                    "volume": 10000.0,
                    "bestFiveData": [{"buyPrice": 149.5, "sellPrice": 150.5}],
                },
                {
                    "tradingSymbol": "NIFTY25MAY24000PE",
                    "strikePrice": 24000.0,
                    "ltp": 120.0,
                    "opnInterest": 40000.0,
                    "netChangeInOI": -1000.0,
                    "impliedVolatility": 17.5,
                    "volume": 8000.0,
                    "bestFiveData": [{"buyPrice": 119.5, "sellPrice": 120.5}],
                },
                {
                    "tradingSymbol": "NIFTY25MAY24500CE",
                    "strikePrice": 24500.0,
                    "ltp": 50.0,
                    "opnInterest": 30000.0,
                    "netChangeInOI": 500.0,
                    "impliedVolatility": 16.0,
                    "volume": 5000.0,
                    "bestFiveData": [{"buyPrice": 49.5, "sellPrice": 50.5}],
                },
                {
                    "tradingSymbol": "NIFTY25MAY24500PE",
                    "strikePrice": 24500.0,
                    "ltp": 200.0,
                    "opnInterest": 60000.0,
                    "netChangeInOI": 3000.0,
                    "impliedVolatility": 19.0,
                    "volume": 12000.0,
                    "bestFiveData": [{"buyPrice": 199.5, "sellPrice": 200.5}],
                },
            ],
            "unfetched": [],
        },
    }


@pytest.fixture
def sample_candle_response():
    """Three IST-timestamped bars for an F&O instrument."""
    return {
        "status": True,
        "message": "SUCCESS",
        "data": [
            ["2025-01-02T09:15:00+05:30", 150.0, 160.0, 145.0, 155.0, 5000],
            ["2025-01-03T09:15:00+05:30", 155.0, 165.0, 150.0, 162.0, 6000],
            ["2025-01-06T09:15:00+05:30", 162.0, 170.0, 158.0, 168.0, 7000],
        ],
    }


@pytest.fixture
def mock_smart_client_chain(sample_option_chain_response):
    client = MagicMock()
    client.getMarketData.return_value = sample_option_chain_response
    return client


@pytest.fixture
def mock_smart_client_ohlcv(sample_candle_response):
    client = MagicMock()
    client.getCandleData.return_value = sample_candle_response
    return client


def _call_fetch_chain(smart_client, config):
    return fetch_option_chain(
        underlying="NIFTY",
        expiry="29MAY2025",
        smart_client=smart_client,
        config=config,
    )


def _call_fetch_fo_ohlcv(smart_client, config):
    return fetch_fo_ohlcv(
        symbol="NIFTY25MAY24000CE",
        token="99926009",
        interval="ONE_DAY",
        from_date="2025-01-02 09:15",
        to_date="2025-01-06 15:30",
        smart_client=smart_client,
        config=config,
    )


# ── fetch_option_chain tests ───────────────────────────────────────────────────


class TestFetchOptionChain:
    def test_returns_correct_columns(self, mock_smart_client_chain, mock_config):
        """Returns DataFrame with exactly the expected option chain columns and all rows."""
        with patch("markets.india.fo_fetcher.AuditTrail"):
            df = _call_fetch_chain(mock_smart_client_chain, mock_config)

        assert list(df.columns) == [
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
        assert len(df) == 4
        assert (df["iv"] > 0).all()

    def test_ce_and_pe_rows_both_present(self, mock_smart_client_chain, mock_config):
        """Both CE and PE option_type values are present in the returned DataFrame."""
        with patch("markets.india.fo_fetcher.AuditTrail"):
            df = _call_fetch_chain(mock_smart_client_chain, mock_config)

        assert "CE" in df["option_type"].values
        assert "PE" in df["option_type"].values

    def test_rows_with_zero_iv_are_rejected(self, mock_config):
        """Rows where IV <= 0 are excluded from output and a REJECTION is audit-logged."""
        response = {
            "status": True,
            "message": "SUCCESS",
            "data": {
                "fetched": [
                    {
                        "tradingSymbol": "NIFTY25MAY24000CE",
                        "strikePrice": 24000.0,
                        "ltp": 150.0,
                        "opnInterest": 50000.0,
                        "netChangeInOI": 1000.0,
                        "impliedVolatility": 0.0,  # invalid — IV=0 must be rejected
                        "volume": 10000.0,
                        "bestFiveData": [{"buyPrice": 149.5, "sellPrice": 150.5}],
                    },
                    {
                        "tradingSymbol": "NIFTY25MAY24000PE",
                        "strikePrice": 24000.0,
                        "ltp": 120.0,
                        "opnInterest": 40000.0,
                        "netChangeInOI": -500.0,
                        "impliedVolatility": 17.5,  # valid
                        "volume": 8000.0,
                        "bestFiveData": [{"buyPrice": 119.5, "sellPrice": 120.5}],
                    },
                ],
                "unfetched": [],
            },
        }
        smart_client = MagicMock()
        smart_client.getMarketData.return_value = response
        mock_audit = MagicMock()

        with patch("markets.india.fo_fetcher.AuditTrail", return_value=mock_audit):
            df = _call_fetch_chain(smart_client, mock_config)

        assert len(df) == 1
        assert df.iloc[0]["option_type"] == "PE"
        assert (df["iv"] > 0).all()
        mock_audit.append.assert_called_once()
        call_kwargs = mock_audit.append.call_args[1]
        assert call_kwargs["event_type"] == "REJECTION"

    def test_audit_trail_rejection_on_api_failure(
        self, mock_config, sample_option_chain_response
    ):
        """AuditTrail.append is called with event_type='REJECTION' on getMarketData failure."""
        smart_client = MagicMock()
        smart_client.getMarketData.side_effect = [
            RuntimeError("connection refused"),
            sample_option_chain_response,
        ]
        mock_audit = MagicMock()

        with (
            patch("markets.india.fo_fetcher.AuditTrail", return_value=mock_audit),
            patch("markets.india.fo_fetcher.time.sleep"),
        ):
            _call_fetch_chain(smart_client, mock_config)

        first_rejection = mock_audit.append.call_args_list[0]
        assert first_rejection[1]["event_type"] == "REJECTION"

    def test_empty_fetched_list_returns_empty_dataframe(self, mock_config):
        """API success with empty fetched list returns empty DataFrame with correct columns."""
        smart_client = MagicMock()
        smart_client.getMarketData.return_value = {
            "status": True,
            "message": "SUCCESS",
            "data": {"fetched": [], "unfetched": []},
        }
        with patch("markets.india.fo_fetcher.AuditTrail"):
            df = _call_fetch_chain(smart_client, mock_config)

        assert df.empty
        assert list(df.columns) == [
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


# ── fetch_fo_ohlcv tests ───────────────────────────────────────────────────────


class TestFetchFoOhlcv:
    def test_returns_correct_columns(self, mock_smart_client_ohlcv, mock_config):
        """Returns DataFrame with exactly the OHLCV columns and correct row count."""
        with patch("markets.india.fo_fetcher.AuditTrail"):
            df = _call_fetch_fo_ohlcv(mock_smart_client_ohlcv, mock_config)

        assert list(df.columns) == [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
        assert len(df) == 3

    def test_kill_switch_triggered_on_6th_failure(self, mock_config):
        """halt(market='india') is called when getCandleData fails all 6 attempts."""
        smart_client = MagicMock()
        smart_client.getCandleData.side_effect = ConnectionError("NFO unreachable")

        with (
            patch("markets.india.fo_fetcher.AuditTrail"),
            patch("markets.india.fo_fetcher.time.sleep"),
            patch("markets.india.fo_fetcher.halt") as mock_halt,
        ):
            with pytest.raises(ConnectionError):
                _call_fetch_fo_ohlcv(smart_client, mock_config)

        mock_halt.assert_called_once_with(
            market="india",
            reason=ANY,
            triggered_by="fo_fetcher",
        )

    def test_audit_trail_rejection_on_failure(
        self, mock_config, sample_candle_response
    ):
        """AuditTrail.append is called with event_type='REJECTION' on getCandleData failure."""
        smart_client = MagicMock()
        smart_client.getCandleData.side_effect = [
            RuntimeError("timeout"),
            sample_candle_response,
        ]
        mock_audit = MagicMock()

        with (
            patch("markets.india.fo_fetcher.AuditTrail", return_value=mock_audit),
            patch("markets.india.fo_fetcher.time.sleep"),
        ):
            _call_fetch_fo_ohlcv(smart_client, mock_config)

        first_rejection = mock_audit.append.call_args_list[0]
        assert first_rejection[1]["event_type"] == "REJECTION"
