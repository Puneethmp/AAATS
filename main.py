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
from foundation.shutdown_handler import register_shutdown

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
        choices=["us", "india", "india_fo", "crypto", "all"],
        default="all",
        help="Which market module to start.",
    )
    args = parser.parse_args()

    _log.info(f"AAATS starting. mode={args.mode} market={args.market}")

    # Register graceful shutdown handler for SIGINT/SIGTERM
    register_shutdown()

    # Check halt state before doing anything
    from foundation.kill_switch import is_halted

    halted_markets = [m for m in ("us", "india", "crypto") if is_halted(m)]
    if halted_markets:
        _log.warning(
            f"The following markets are currently HALTED: {halted_markets}. "
            "Resume requires: python kill.py --reset --market <market> --authorized-by <name> --reason <reason>"
        )

    # Mode validation via ModeManager
    from foundation.mode_manager import ModeManager
    mm = ModeManager()
    mm.start_paper_trading()
    if args.mode == "live":
        if mm.is_paper():
            _log.warning(
                "LIVE mode requested but system is in PAPER mode. "
                "Use: python scripts/mode_manager.py --switch-to-live to activate."
            )
        _log.warning(
            "LIVE mode: real orders with real capital. "
            "Ensure 4+ weeks of paper trading evidence before proceeding."
        )

    # RBAC: verify user has paper_trading permission
    from foundation.rbac import RBACManager
    rbac = RBACManager()
    try:
        permission = "live_trading" if args.mode == "live" else "paper_trading"
        rbac.require_permission(permission, user="system")
    except PermissionError as e:
        _log.error(f"RBAC check failed: {e}")
        sys.exit(1)

    _log.info("Foundation layer loaded.")

    from execution.orchestrator import run_all
    run_all(market=args.market)


if __name__ == "__main__":
    main()
