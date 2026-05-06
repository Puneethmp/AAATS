"""
AAATS Orchestrator — runs all market runners in parallel threads.

Usage:
    python main.py --mode paper --market all
    python main.py --mode paper --market crypto
    python main.py --mode paper --market india
"""

from __future__ import annotations

import threading
from dotenv import dotenv_values

from foundation.logger import get_logger
from foundation.secrets_manager import SecretsManager
from foundation.shutdown_handler import get_shutdown

_log = get_logger("execution", "orchestrator")

_sm = SecretsManager()


def _load_india_creds() -> dict:
    """Load India credentials from encrypted vault, fall back to .env."""
    return {
        "api_key":     _sm.get("ANGEL_ONE_API_KEY") or dotenv_values(".env").get("INDIA__ANGEL_API_KEY", ""),
        "client_id":   _sm.get("ANGEL_ONE_CLIENT_ID") or dotenv_values(".env").get("INDIA__ANGEL_CLIENT_ID", ""),
        "pin":         _sm.get("ANGEL_ONE_PIN") or dotenv_values(".env").get("INDIA__ANGEL_PIN", ""),
        "totp_secret": _sm.get("ANGEL_ONE_TOTP_SECRET") or dotenv_values(".env").get("INDIA__ANGEL_TOTP_SECRET", ""),
    }


def start_crypto(poll_seconds: int = 3600) -> threading.Thread:
    from execution.crypto_runner import run_loop
    t = threading.Thread(target=run_loop, kwargs={"poll_seconds": poll_seconds},
                         daemon=True, name="crypto-runner")
    t.start()
    _log.info("Crypto runner thread started.")
    return t


def start_india(poll_seconds: int = 900) -> threading.Thread:
    from execution.india_runner import run_loop
    creds = _load_india_creds()
    if not creds["api_key"]:
        _log.error("India credentials missing in .env — skipping India runner.")
        return None
    t = threading.Thread(
        target=run_loop,
        kwargs={**creds, "poll_seconds": poll_seconds},
        daemon=True, name="india-runner",
    )
    t.start()
    _log.info("India equity runner thread started.")
    return t


def run_all(market: str = "all") -> None:
    """Start all enabled market runners and block until Ctrl-C."""
    threads = []

    if market in ("crypto", "all"):
        threads.append(start_crypto())

    if market in ("india", "all"):
        threads.append(start_india())

    if not threads:
        _log.error(f"No threads started for market={market}")
        return

    shutdown = get_shutdown()
    _log.info(f"Orchestrator running {len(threads)} market(s). Press Ctrl-C to stop.")
    try:
        import time
        while not shutdown.is_requested():
            time.sleep(30)
    except KeyboardInterrupt:
        pass
    _log.info("Orchestrator stopped.")
