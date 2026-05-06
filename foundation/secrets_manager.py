"""
Encrypted credentials manager for AAATS.

Encrypts API keys using Fernet (symmetric AES-128-CBC + HMAC-SHA256).
Keys are stored in data/secrets.enc, master password in env var AAATS_MASTER_KEY.

Usage:
    from foundation.secrets_manager import SecretsManager
    sm = SecretsManager()
    api_key = sm.get("BINANCE_API_KEY")
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("system", "secrets_manager")

_SECRETS_FILE = Path("data/secrets.enc")
_ENV_MASTER_KEY = "AAATS_MASTER_KEY"


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        return Fernet
    except ImportError:
        raise RuntimeError("Install cryptography: pip install cryptography")


def _derive_key(password: str) -> bytes:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    import hashlib
    salt = b"AAATS_SALT_v1_2024"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480000)
    key_bytes = kdf.derive(password.encode())
    return base64.urlsafe_b64encode(key_bytes)


class SecretsManager:
    """
    Encrypted key-value store for API credentials.
    Falls back to environment variables if secrets file not found
    (allows gradual migration and CI/CD compatibility).
    """

    def __init__(self, secrets_file: Path | None = None) -> None:
        self._file = secrets_file or _SECRETS_FILE
        self._cache: dict[str, str] | None = None

    def _master_key(self) -> str:
        key = os.environ.get(_ENV_MASTER_KEY, "")
        if not key:
            _log.warning("AAATS_MASTER_KEY not set — falling back to env vars for all secrets")
        return key

    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        master = self._master_key()
        if not master or not self._file.exists():
            self._cache = {}
            return self._cache
        Fernet = _get_fernet()
        key = _derive_key(master)
        f = Fernet(key)
        encrypted = self._file.read_bytes()
        plaintext = f.decrypt(encrypted)
        self._cache = json.loads(plaintext.decode())
        _log.info(f"Secrets loaded from {self._file} ({len(self._cache)} keys)")
        return self._cache

    def get(self, key: str, default: str = "") -> str:
        """Return secret by key. Falls back to os.environ if not in vault."""
        secrets = self._load()
        if key in secrets:
            return secrets[key]
        env_val = os.environ.get(key, default)
        if env_val:
            _log.debug(f"Secret '{key}' read from environment (not encrypted vault)")
        return env_val

    def save(self, secrets: dict[str, str]) -> None:
        """Encrypt and save secrets dict to disk."""
        master = self._master_key()
        if not master:
            raise RuntimeError(f"Set {_ENV_MASTER_KEY} environment variable first")
        Fernet = _get_fernet()
        key = _derive_key(master)
        f = Fernet(key)
        plaintext = json.dumps(secrets, indent=2).encode()
        encrypted = f.encrypt(plaintext)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_bytes(encrypted)
        self._cache = secrets
        _log.info(f"Secrets encrypted and saved to {self._file}")

    def rotate(self, new_master: str) -> None:
        """Re-encrypt vault under a new master password."""
        old_secrets = self._load()
        old_master = self._master_key()
        os.environ[_ENV_MASTER_KEY] = new_master
        self._cache = None
        self.save(old_secrets)
        _log.info("Secrets vault rotated to new master key")
        os.environ[_ENV_MASTER_KEY] = old_master
