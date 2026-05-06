"""
Tests for markets/india/token_manager.py.
All Angel One API calls are mocked — zero real network calls.
"""

from datetime import date, timedelta
from unittest.mock import ANY, MagicMock, patch

import pytest

from markets.india.token_manager import TokenManager

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.india.angel_client_id = "TEST_CLIENT"
    cfg.india.angel_pin = "TEST_PIN"
    cfg.india.angel_totp_secret = "JBSWY3DPEHPK3PXP"  # valid base32 test secret
    return cfg


@pytest.fixture
def success_response():
    return {
        "status": True,
        "message": "SUCCESS",
        "data": {
            "jwtToken": "test_jwt_token",
            "refreshToken": "test_refresh_token",
            "feedToken": "test_feed_token",
        },
    }


@pytest.fixture
def mock_client(success_response):
    client = MagicMock()
    client.generateSession.return_value = success_response
    return client


@pytest.fixture
def token_manager(mock_client, mock_config):
    """TokenManager with patched AuditTrail to avoid DB side effects."""
    with patch("markets.india.token_manager.AuditTrail"):
        return TokenManager(smart_connect_client=mock_client, config=mock_config)


# ── renew_session tests ───────────────────────────────────────────────────────


class TestRenewSession:
    def test_returns_correct_dict_on_success(self, token_manager):
        """renew_session maps jwtToken / refreshToken / feedToken to the canonical keys."""
        result = token_manager.renew_session()
        assert result == {
            "auth_token": "test_jwt_token",
            "refresh_token": "test_refresh_token",
            "feed_token": "test_feed_token",
        }

    def test_totp_generated_from_correct_secret(self, mock_client, mock_config):
        """pyotp.TOTP is constructed with the TOTP secret from config, not a hardcoded value."""
        with (
            patch("markets.india.token_manager.AuditTrail"),
            patch("markets.india.token_manager.pyotp") as mock_pyotp,
        ):
            mock_totp_instance = MagicMock()
            mock_totp_instance.now.return_value = "123456"
            mock_pyotp.TOTP.return_value = mock_totp_instance

            tm = TokenManager(mock_client, mock_config)
            tm.renew_session()

            mock_pyotp.TOTP.assert_called_once_with("JBSWY3DPEHPK3PXP")
            mock_totp_instance.now.assert_called_once()

    def test_kill_switch_halted_on_auth_failure(self, mock_client, mock_config):
        """halt(market='india') is called when generateSession returns status=False."""
        mock_client.generateSession.return_value = {
            "status": False,
            "message": "Invalid credentials",
        }
        alert_fn = MagicMock()
        with (
            patch("markets.india.token_manager.AuditTrail"),
            patch("markets.india.token_manager.halt") as mock_halt,
        ):
            tm = TokenManager(mock_client, mock_config, alert_fn=alert_fn)
            with pytest.raises(RuntimeError):
                tm.renew_session()

        mock_halt.assert_called_once_with(
            market="india",
            reason=ANY,
            triggered_by="token_manager",
        )

    def test_alert_fn_called_on_auth_failure(self, mock_client, mock_config):
        """alert_fn is invoked with a non-empty message when authentication fails."""
        mock_client.generateSession.return_value = {
            "status": False,
            "message": "Invalid credentials",
        }
        alert_fn = MagicMock()
        with (
            patch("markets.india.token_manager.AuditTrail"),
            patch("markets.india.token_manager.halt"),
        ):
            tm = TokenManager(mock_client, mock_config, alert_fn=alert_fn)
            with pytest.raises(RuntimeError):
                tm.renew_session()

        alert_fn.assert_called_once()
        message_arg = alert_fn.call_args[0][0]
        assert isinstance(message_arg, str) and len(message_arg) > 0

    def test_kill_switch_and_alert_called_on_exception(self, mock_client, mock_config):
        """Both halt and alert_fn are triggered when generateSession raises an exception."""
        mock_client.generateSession.side_effect = ConnectionError("Network timeout")
        alert_fn = MagicMock()
        with (
            patch("markets.india.token_manager.AuditTrail"),
            patch("markets.india.token_manager.halt") as mock_halt,
        ):
            tm = TokenManager(mock_client, mock_config, alert_fn=alert_fn)
            with pytest.raises(RuntimeError):
                tm.renew_session()

        mock_halt.assert_called_once()
        alert_fn.assert_called_once()


# ── get_auth_token tests ──────────────────────────────────────────────────────


class TestGetAuthToken:
    def test_raises_if_renew_session_not_called(self, token_manager):
        """get_auth_token raises RuntimeError before any session renewal."""
        with pytest.raises(RuntimeError, match="renew_session"):
            token_manager.get_auth_token()

    def test_returns_cached_token_after_renewal(self, token_manager):
        """get_auth_token returns the JWT token cached by renew_session."""
        token_manager.renew_session()
        assert token_manager.get_auth_token() == "test_jwt_token"


# ── is_token_valid tests ──────────────────────────────────────────────────────


class TestIsTokenValid:
    def test_false_before_renewal(self, token_manager):
        """is_token_valid is False with no prior renew_session call."""
        assert token_manager.is_token_valid() is False

    def test_true_when_renewed_today(self, token_manager):
        """is_token_valid is True immediately after renew_session succeeds."""
        token_manager.renew_session()
        assert token_manager.is_token_valid() is True

    def test_false_when_renewed_yesterday(self, token_manager):
        """is_token_valid is False when the cached renewal date is yesterday (IST)."""
        token_manager.renew_session()
        # Simulate that the renewal happened yesterday
        token_manager._renewal_date = date.today() - timedelta(days=1)
        assert token_manager.is_token_valid() is False
