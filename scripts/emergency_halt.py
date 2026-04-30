"""
Emergency halt CLI — immediately stops all or specific market trading.

Usage:
    python scripts/emergency_halt.py --market all --reason "Unexpected drawdown"
    python scripts/emergency_halt.py --market crypto --reason "Binance API down"
    python scripts/emergency_halt.py --market india --reason "Angel One auth failure"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from foundation.kill_switch import halt


def main() -> None:
    parser = argparse.ArgumentParser(description="AAATS Emergency Halt")
    parser.add_argument(
        "--market",
        choices=["us", "india", "crypto", "all"],
        required=True,
        help="Market to halt",
    )
    parser.add_argument("--reason", required=True, help="Reason for halt (logged to audit trail)")
    args = parser.parse_args()

    print(f"\n⚠️  EMERGENCY HALT — market={args.market}")
    print(f"   Reason: {args.reason}")
    confirm = input("   Type 'HALT' to confirm: ").strip()
    if confirm != "HALT":
        print("Aborted.")
        sys.exit(0)

    halt(market=args.market, reason=args.reason, triggered_by="emergency_halt.py CLI")
    print(f"\n🛑 HALTED: {args.market.upper()}")
    print("   Resume with: python scripts/emergency_resume.py")


if __name__ == "__main__":
    main()
