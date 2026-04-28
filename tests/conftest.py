"""
Shared pytest fixtures and environment setup for AAATS test suite.
Sets minimal required env vars so Pydantic config models can be instantiated in tests.
"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def set_test_env():
    """Inject minimal environment variables for all tests."""
    defaults = {
        "US__ALPACA_API_KEY": "test_key",
        "US__ALPACA_SECRET_KEY": "test_secret",
        "INDIA__ANGEL_API_KEY": "test_key",
        "INDIA__ANGEL_CLIENT_ID": "test_client",
        "INDIA__ANGEL_PASSWORD": "test_password",
        "INDIA__ANGEL_TOTP_SECRET": "JBSWY3DPEHPK3PXP",
        "ALERTS__TELEGRAM_BOT_TOKEN": "test_token",
        "ALERTS__TELEGRAM_CHAT_ID": "123456789",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
