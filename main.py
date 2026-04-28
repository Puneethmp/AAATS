"""
AAATS system entry point.
Phase 0: validates foundation layer, checks halt state, confirms system is ready.
Phase 1+: full market pipelines are started from here.

Usage:
    python main.py --mode paper
    python main.py --mode paper --market us
    python main.py --mode paper --market india
"""

import argparse
import sys

from foundation.logger import get_logger

_log = get_logger("system", "main")


def main() -> None:
    parser = argparse.ArgumentParser(description="AAATS Trading System")
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode. 'live' requires 3+ months of paper trading evidence per market.",
    )
    parser.add_argument(
        "--market",
        choices=["us", "india", "india_fo", "all"],
        default="all",
        help="Which market module to start.",
    )
    args = parser.parse_args()

    _log.info(f"AAATS starting. mode={args.mode} market={args.market}")

    # Check halt state before doing anything
    from foundation.kill_switch import is_halted

    halted_markets = [m for m in ("us", "india", "crypto") if is_halted(m)]
    if halted_markets:
        _log.warning(
            f"The following markets are currently HALTED: {halted_markets}. "
            "Resume requires: python kill.py --reset --market <market> --authorized-by <name> --reason <reason>"
        )

    if args.mode == "live":
        _log.warning(
            "LIVE mode requested. This will place real orders with real capital. "
            "Ensure 3+ months of paper trading evidence exists per market before proceeding."
        )

    # Phase 0: foundation layer is the only active component
    _log.info("Phase 0 foundation layer loaded successfully. Data pipelines pending Phase 1.")

    # Phase 1+ market pipelines will be started here


if __name__ == "__main__":
    main()
