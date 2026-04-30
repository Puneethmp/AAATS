"""
Emergency resume CLI — clears halt state and resumes trading.

Usage:
    python scripts/emergency_resume.py --market all --authorized-by Puneeth --reason "Issue resolved"
    python scripts/emergency_resume.py --market crypto --authorized-by Puneeth --reason "API back up"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from foundation.kill_switch import reset, is_halted


def main() -> None:
    parser = argparse.ArgumentParser(description="AAATS Emergency Resume")
    parser.add_argument(
        "--market",
        choices=["us", "india", "crypto", "all"],
        required=True,
        help="Market to resume",
    )
    parser.add_argument("--authorized-by", required=True, help="Name of authorizing person")
    parser.add_argument("--reason", required=True, help="Reason the halt is being cleared")
    args = parser.parse_args()

    markets_check = ["us", "india", "crypto"] if args.market == "all" else [args.market]
    halted = [m for m in markets_check if is_halted(m)]

    if not halted:
        print(f"No halt active for {args.market}. Nothing to resume.")
        sys.exit(0)

    print(f"\n▶️  RESUME REQUEST — market={args.market}")
    print(f"   Halted markets: {halted}")
    print(f"   Authorized by: {args.authorized_by}")
    print(f"   Reason: {args.reason}")
    confirm = input("   Type 'RESUME' to confirm: ").strip()
    if confirm != "RESUME":
        print("Aborted.")
        sys.exit(0)

    reset(market=args.market, authorized_by=args.authorized_by, reason=args.reason)
    print(f"\n✅ RESUMED: {args.market.upper()}")
    print("   Trading will resume on the next cycle.")


if __name__ == "__main__":
    main()
