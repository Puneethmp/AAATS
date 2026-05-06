#!/usr/bin/env python3
"""
Standalone Paper Trading Loop Runner for Docker Deployment.

This script is the entry point for docker-compose services that run
paper trading loops for US, India, and Crypto markets.

Usage:
    python trading/paper_loop_runner.py --market us
    python trading/paper_loop_runner.py --market india
    python trading/paper_loop_runner.py --market crypto

Environment Variables:
    MARKET: Market to trade (us, india, crypto)
    SYSTEM__TRADING_MODE: Trading mode (paper, live)
    
Docker Command:
    python trading/paper_loop_runner.py --market ${MARKET}
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add project root to path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from foundation.logger import get_logger
from foundation.shutdown_handler import register_shutdown, get_shutdown
from foundation.kill_switch import is_halted

_log = get_logger("trading", "paper_loop_runner")


def run_us_market(poll_seconds: int = 900) -> None:
    """Run US market paper trading loop."""
    _log.info("Starting US market paper trading loop...")
    
    # Import US market runner
    try:
        from execution.us_runner import run_loop
        _log.info("US runner imported successfully")
        run_loop(poll_seconds=poll_seconds)
    except ImportError as e:
        _log.error(f"US runner not implemented yet: {e}")
        _log.info("US market runner will be implemented in future phase")
        # Keep container alive for now
        while not get_shutdown().is_requested():
            time.sleep(60)


def run_india_market(poll_seconds: int = 900) -> None:
    """Run India market paper trading loop."""
    _log.info("Starting India market paper trading loop...")
    
    # Load India credentials from environment
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    api_key = os.getenv("INDIA__ANGEL_API_KEY", "")
    client_id = os.getenv("INDIA__ANGEL_CLIENT_ID", "")
    pin = os.getenv("INDIA__ANGEL_PIN", "")
    totp_secret = os.getenv("INDIA__ANGEL_TOTP_SECRET", "")
    
    if not all([api_key, client_id, pin, totp_secret]):
        _log.error("India credentials missing from environment variables")
        _log.error("Required: INDIA__ANGEL_API_KEY, INDIA__ANGEL_CLIENT_ID, INDIA__ANGEL_PIN, INDIA__ANGEL_TOTP_SECRET")
        _log.info("Container will stay alive but trading is disabled")
        # Keep container alive
        while not get_shutdown().is_requested():
            time.sleep(60)
        return
    
    # Import India runner
    from execution.india_runner import run_loop
    
    _log.info("India runner starting with credentials loaded")
    run_loop(
        api_key=api_key,
        client_id=client_id,
        pin=pin,
        totp_secret=totp_secret,
        poll_seconds=poll_seconds,
    )


def run_crypto_market(poll_seconds: int = 1800) -> None:
    """Run Crypto market paper trading loop."""
    _log.info("Starting Crypto market paper trading loop...")
    
    # Import Crypto runner
    from execution.crypto_runner import run_loop
    
    _log.info("Crypto runner starting")
    run_loop(poll_seconds=poll_seconds)


def main() -> None:
    """Main entry point for paper trading loop runner."""
    parser = argparse.ArgumentParser(
        description="AAATS Paper Trading Loop Runner"
    )
    parser.add_argument(
        "--market",
        choices=["us", "india", "crypto"],
        required=True,
        help="Market to trade",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=None,
        help="Polling interval in seconds (default: market-specific)",
    )
    
    args = parser.parse_args()
    
    # Register shutdown handler
    register_shutdown()
    
    # Check halt state
    if is_halted(args.market):
        _log.warning(
            f"{args.market.upper()} market is HALTED. "
            "Trading will not start until halt is cleared."
        )
        _log.info("Container will stay alive but trading is disabled")
        # Keep container alive
        while not get_shutdown().is_requested():
            time.sleep(60)
        return
    
    # Determine poll interval
    poll_seconds = args.poll_seconds
    if poll_seconds is None:
        poll_seconds = {
            "us": 900,      # 15 minutes
            "india": 900,   # 15 minutes
            "crypto": 1800, # 30 minutes
        }[args.market]
    
    _log.info(
        f"Starting {args.market.upper()} paper trading loop "
        f"(poll interval: {poll_seconds}s)"
    )
    
    # Route to appropriate market runner
    try:
        if args.market == "us":
            run_us_market(poll_seconds)
        elif args.market == "india":
            run_india_market(poll_seconds)
        elif args.market == "crypto":
            run_crypto_market(poll_seconds)
    except KeyboardInterrupt:
        _log.info(f"{args.market.upper()} runner stopped by user")
    except Exception as e:
        _log.exception(f"{args.market.upper()} runner crashed: {e}")
        sys.exit(1)
    
    _log.info(f"{args.market.upper()} runner shutdown complete")


if __name__ == "__main__":
    main()
