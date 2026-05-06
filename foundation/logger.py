"""
Structured logging factory for AAATS.
Returns Loguru loggers bound to a specific market and module.
Every log entry carries market and module tags in its structured JSON output.

Usage:
    from foundation.logger import get_logger
    log = get_logger("us", "fetcher")
    log.info("Fetched 100 bars", symbol="AAPL")
"""

import sys
from pathlib import Path

from loguru import logger as _base_logger

# Remove default stderr sink so we control all output formatting
_base_logger.remove()

# Set global defaults so records always have market/module keys (prevents KeyError in format strings)
_base_logger.configure(extra={"market": "SYSTEM", "module": "core"})

# Console sink — human-readable, colored, always-on
_base_logger.add(
    sys.stdout,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<cyan>{extra[market]:<12}</cyan> | "
        "<cyan>{extra[module]:<20}</cyan> | "
        "<level>{level:<8}</level> | "
        "{message}"
    ),
    level="DEBUG",
    colorize=True,
    enqueue=True,
)

# Registry prevents adding duplicate file sinks on repeated get_logger calls
_registered_sinks: set[str] = set()


def get_logger(market: str, module: str):
    """
    Return a Loguru logger bound to the given market and module.

    Creates a per-market/module JSON log file under logs/{market}/{module}.log
    on first call. Subsequent calls with the same (market, module) reuse the
    existing sink without duplication.

    Args:
        market: Market identifier — "us", "india", "crypto", or "system".
        module: Module name — e.g. "fetcher", "validator", "kill_switch".

    Returns:
        A Loguru logger with market and module pre-bound in extra fields.
    """
    sink_key = f"{market}::{module}"

    if sink_key not in _registered_sinks:
        import os as _os
        log_dir = Path(_os.environ.get("AAATS_LOGS", "logs")) / market
        log_dir.mkdir(parents=True, exist_ok=True)

        _base_logger.add(
            str(log_dir / f"{module}.log"),
            format="{time:ISO8601} | {extra[market]} | {extra[module]} | {function} | {level} | {message} | {extra}",
            rotation="00:00",          # New file each midnight
            retention="90 days",
            serialize=True,            # JSON output
            enqueue=True,              # Thread-safe async writes
            level="DEBUG",
            # Only write records that belong to this exact market+module combo
            filter=lambda r, m=market, mod=module: (
                r["extra"].get("market") == m and r["extra"].get("module") == mod
            ),
        )
        _registered_sinks.add(sink_key)

    return _base_logger.bind(market=market, module=module)
