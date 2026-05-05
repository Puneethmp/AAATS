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


# ── SQLite on NTFS mount fix ─────────────────────────────────────────────────
# SQLite file locking fails on Windows NTFS mounts in Linux sandbox.
# Each AuditTrail instance gets its own unique /tmp DB so tests stay isolated.

import itertools as _itertools
import tempfile as _tempfile
from unittest import mock as _mock
from pathlib import Path as _Path

_AUDIT_COUNTER = _itertools.count()
_AUDIT_TMP_ROOT = _tempfile.mkdtemp(prefix="aaats_audit_")


def _patched_audit_init(self, db_path: str = None) -> None:
    """Give every AuditTrail instance a unique /tmp DB — avoids NTFS I/O errors."""
    import sqlalchemy as _sa
    from sqlalchemy.pool import StaticPool as _StaticPool

    idx = next(_AUDIT_COUNTER)
    _tmp_db = f"{_AUDIT_TMP_ROOT}/audit_{idx}.db"
    self._engine = _sa.create_engine(
        f"sqlite:///{_tmp_db}",
        connect_args={"check_same_thread": False},
        poolclass=_StaticPool,
    )
    self._db_path = _tmp_db
    self._init_schema()


@pytest.fixture(autouse=True, scope="session")
def redirect_audit_trail_to_tmp():
    """Redirect AuditTrail to /tmp for the entire test session."""
    with _mock.patch("foundation.audit_trail.AuditTrail.__init__", _patched_audit_init):
        yield
