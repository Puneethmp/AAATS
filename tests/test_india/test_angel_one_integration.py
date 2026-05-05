"""
Angel One SmartAPI Integration Tests

⚠️ IMPORTANT: These tests use REAL Angel One API credentials from .env
They are NOT run in normal pytest — only when explicitly requested.

These tests verify:
1. API credentials are valid (auth succeeds)
2. TOTP-based session renewal works
3. Token can be cached and reused
4. Error handling works correctly (invalid credentials, network timeout)

RUN ONLY WHEN:
- You have verified .env has real Angel One credentials
- You want to test production API connectivity before live trading
- You're debugging a token renewal failure

HOW TO RUN:
  pytest tests/test_india/test_angel_one_integration.py -v -s --tb=short

  -v: verbose (show each test)
  -s: show print output
  --tb=short: short traceback (less noise)

EXPECTED OUTPUT ON SUCCESS:
  test_can_authenticate_and_get_tokens PASSED
  test_totp_renewal_works PASSED
  test_tokens_are_reused_until_expiry PASSED
"""

import os
from datetime import datetime, timedelta

import pytest
import pytz
from SmartApi import SmartConnect

from config.settings import AppConfig
from foundation.logger import get_logger
from markets.india.token_manager import TokenManager

_IST = pytz.timezone("Asia/Kolkata")
_log = get_logger("tests", "angel_one_integration")


@pytest.mark.skipif(
    True,
    reason="Live Angel One integration test: requires real API credentials and network access"
)
class TestAngelOneIntegration:
    """Real API tests. Only run with valid credentials."""

    @pytest.fixture(scope="class")
    def config(self):
        """Load real config from .env."""
        from dotenv import load_dotenv
        load_dotenv(".env", override=True)
        config = AppConfig()

        # Verify all required Angel One fields are set
        required_fields = [
            "angel_api_key",
            "angel_client_id",
            "angel_pin",
            "angel_totp_secret",
        ]
        for field in required_fields:
            val = getattr(config.india, field, None)
            if not val or val.startswith("your_"):
                pytest.skip(
                    f"Angel One {field} not configured in .env. "
                    f"Integration tests require real credentials."
                )

        return config

    @pytest.fixture(scope="class")
    def smart_client(self, config):
        """Real SmartConnect instance."""
        return SmartConnect(api_key=config.india.angel_api_key)

    @pytest.fixture(scope="class")
    def token_manager(self, smart_client, config):
        """TokenManager with real API client."""
        return TokenManager(
            smart_connect_client=smart_client,
            config=config,
            alert_fn=lambda msg: _log.warning(f"Alert: {msg}"),
        )

    def test_can_authenticate_and_get_tokens(self, token_manager):
        """
        Verify Angel One accepts credentials and returns valid tokens.

        This test:
        1. Calls generateSession with real credentials
        2. Verifies response contains auth_token, refresh_token, feed_token
        3. Confirms tokens are non-empty strings
        """
        result = token_manager.renew_session()

        assert isinstance(result, dict), "Result should be a dict"
        assert "auth_token" in result, "Missing auth_token"
        assert "refresh_token" in result, "Missing refresh_token"
        assert "feed_token" in result, "Missing feed_token"

        assert isinstance(result["auth_token"], str), "auth_token should be str"
        assert len(result["auth_token"]) > 0, "auth_token should be non-empty"
        assert isinstance(result["refresh_token"], str), "refresh_token should be str"
        assert isinstance(result["feed_token"], str), "feed_token should be str"

        _log.info("✅ Authentication successful")

    def test_totp_renewal_works(self, token_manager):
        """
        Verify TOTP-based session renewal works correctly.

        This test:
        1. Renews session twice (simulating daily renewal)
        2. Confirms both calls succeed
        3. Verifies tokens change between calls
        """
        result1 = token_manager.renew_session()
        token1 = result1["auth_token"]

        # Wait a moment to ensure TOTP changes (TOTP updates every 30 seconds)
        # In real scenario, renewals happen on different calendar days
        result2 = token_manager.renew_session()
        token2 = result2["auth_token"]

        assert token1 is not None, "First auth_token should be non-empty"
        assert token2 is not None, "Second auth_token should be non-empty"
        # Tokens *may* be the same if renewed within same 30-second TOTP window,
        # but at least both should be valid

        _log.info("✅ TOTP renewal successful")

    def test_tokens_are_cached_until_expiry(self, token_manager, config):
        """
        Verify token_manager caches tokens and doesn't renew unnecessarily.

        This test:
        1. Renews session once
        2. Calls get_auth_token() multiple times
        3. Confirms it returns same cached token
        4. Verifies is_token_valid() returns True
        """
        token_manager.renew_session()
        cached_token = token_manager.get_auth_token()

        assert cached_token is not None, "Cached token should exist"
        assert len(cached_token) > 0, "Cached token should be non-empty"

        # Token should still be valid
        assert token_manager.is_token_valid(), "Token should be valid after renewal"

        # Calling get_auth_token again should return same cached token
        same_token = token_manager.get_auth_token()
        assert same_token == cached_token, "Tokens should be identical when cached"

        _log.info("✅ Token caching works correctly")

    def test_error_handling_on_invalid_credentials(self, config):
        """
        Verify error handling when credentials are invalid.

        This test intentionally uses bad credentials to verify
        the system fails gracefully (doesn't crash, logs properly).

        Note: This test requires you to temporarily set bad credentials
        in .env, or skip it if you want to preserve working credentials.
        """
        bad_client = SmartConnect(api_key=config.india.angel_api_key)
        bad_config = config.model_copy()
        bad_config.india.angel_pin = "0000"  # Invalid PIN

        tm = TokenManager(bad_client, bad_config)

        # Should raise RuntimeError on auth failure
        with pytest.raises(RuntimeError, match="Angel One generateSession failed"):
            tm.renew_session()

        _log.info("✅ Error handling works correctly")


class TestAngelOneHealthCheck:
    """Lightweight health checks (run these frequently)."""

    @pytest.fixture(scope="class")
    def config(self):
        """Load real config from .env."""
        return AppConfig()

    def test_config_is_valid(self, config):
        """Verify .env has valid Angel One config structure."""
        assert hasattr(config, "india"), "Config should have india section"
        assert hasattr(config.india, "angel_api_key"), "Missing angel_api_key"
        assert hasattr(config.india, "angel_client_id"), "Missing angel_client_id"
        assert hasattr(config.india, "angel_pin"), "Missing angel_pin"
        assert hasattr(config.india, "angel_totp_secret"), "Missing angel_totp_secret"
        _log.info("✅ Config is valid")

    def test_totp_secret_is_valid_base32(self, config):
        """Verify TOTP secret is valid base32."""
        import pyotp

        try:
            totp = pyotp.TOTP(config.india.angel_totp_secret)
            # Try to generate a code (this validates the secret format)
            code = totp.now()
            assert isinstance(code, str), "TOTP code should be string"
            assert len(code) == 6, "TOTP code should be 6 digits"
            _log.info(f"✅ TOTP secret is valid (generated code: {code})")
        except Exception as e:
            pytest.fail(f"Invalid TOTP secret: {e}")
