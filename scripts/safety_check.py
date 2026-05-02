"""
Safety Check CLI — Check safety lock status and manage approvals.

Usage:
    python scripts/safety_check.py status
    python scripts/safety_check.py approve --market us --by "Puneeth" --reason "Paper trading successful"
    python scripts/safety_check.py revoke --market us --by "Puneeth" --reason "Issues detected"
    python scripts/safety_check.py override --by "Puneeth" --reason "Emergency override"
    python scripts/safety_check.py clear-override
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from safety.live_safety_lock import (
    check_safety_lock,
    clear_override,
    grant_manual_approval,
    revoke_manual_approval,
    set_override,
)


def cmd_status(args):
    """Check safety lock status."""
    market = args.market or "all"
    decision = check_safety_lock(market)
    
    print(f"\n{'='*60}")
    print(f"SAFETY LOCK STATUS - {market.upper()}")
    print(f"{'='*60}\n")
    
    print(f"Status: {decision.status.value.upper()}")
    print(f"Allowed: {'✅ YES' if decision.allowed else '❌ NO'}")
    print(f"Reason: {decision.reason}")
    print(f"Readiness Score: {decision.readiness_score:.1f}%")
    print(f"Timestamp: {decision.timestamp}")
    
    if decision.override_by:
        print(f"\n⚠️ OVERRIDE ACTIVE")
        print(f"  By: {decision.override_by}")
        print(f"  Reason: {decision.override_reason}")
    
    print(f"\nChecks:")
    for check, passed in decision.checks_passed.items():
        status = "✅" if passed else "❌"
        print(f"  {status} {check}")
    
    if decision.blockers:
        print(f"\nBlockers:")
        for blocker in decision.blockers:
            print(f"  ❌ {blocker}")
    
    print(f"\n{'='*60}\n")
    
    return 0 if decision.allowed else 1


def cmd_approve(args):
    """Grant manual approval."""
    if not args.market:
        print("ERROR: --market required")
        return 1
    
    if not args.by:
        print("ERROR: --by required (name of person approving)")
        return 1
    
    if not args.reason:
        print("ERROR: --reason required")
        return 1
    
    try:
        grant_manual_approval(
            market=args.market,
            approved_by=args.by,
            reason=args.reason,
        )
        print(f"✅ Manual approval granted for {args.market}")
        return 0
    except Exception as e:
        print(f"❌ Failed to grant approval: {e}")
        return 1


def cmd_revoke(args):
    """Revoke manual approval."""
    if not args.market:
        print("ERROR: --market required")
        return 1
    
    if not args.by:
        print("ERROR: --by required (name of person revoking)")
        return 1
    
    if not args.reason:
        print("ERROR: --reason required")
        return 1
    
    try:
        revoke_manual_approval(
            market=args.market,
            revoked_by=args.by,
            reason=args.reason,
        )
        print(f"✅ Manual approval revoked for {args.market}")
        return 0
    except Exception as e:
        print(f"❌ Failed to revoke approval: {e}")
        return 1


def cmd_override(args):
    """Set manual override (emergency only)."""
    if not args.by:
        print("ERROR: --by required (name of person authorizing)")
        return 1
    
    if not args.reason:
        print("ERROR: --reason required")
        return 1
    
    # Confirmation prompt
    print("\n⚠️  WARNING: You are about to set a manual safety override.")
    print("This bypasses ALL safety checks and should only be used in emergencies.")
    print(f"\nAuthorized by: {args.by}")
    print(f"Reason: {args.reason}")
    
    if not args.confirm:
        response = input("\nType 'OVERRIDE' to confirm: ")
        if response != "OVERRIDE":
            print("❌ Override cancelled")
            return 1
    
    try:
        set_override(
            reason=args.reason,
            authorized_by=args.by,
        )
        print(f"✅ Manual override set (expires in 24 hours)")
        return 0
    except Exception as e:
        print(f"❌ Failed to set override: {e}")
        return 1


def cmd_clear_override(args):
    """Clear manual override."""
    try:
        clear_override()
        print(f"✅ Manual override cleared")
        return 0
    except Exception as e:
        print(f"❌ Failed to clear override: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Safety Lock Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Check safety lock status")
    status_parser.add_argument(
        "--market",
        choices=["us", "india", "crypto", "all"],
        help="Market to check (default: all)",
    )
    
    # Approve command
    approve_parser = subparsers.add_parser("approve", help="Grant manual approval")
    approve_parser.add_argument(
        "--market",
        required=True,
        choices=["us", "india", "crypto", "all"],
        help="Market to approve",
    )
    approve_parser.add_argument(
        "--by",
        required=True,
        help="Name of person granting approval",
    )
    approve_parser.add_argument(
        "--reason",
        required=True,
        help="Reason for approval",
    )
    
    # Revoke command
    revoke_parser = subparsers.add_parser("revoke", help="Revoke manual approval")
    revoke_parser.add_argument(
        "--market",
        required=True,
        choices=["us", "india", "crypto", "all"],
        help="Market to revoke",
    )
    revoke_parser.add_argument(
        "--by",
        required=True,
        help="Name of person revoking approval",
    )
    revoke_parser.add_argument(
        "--reason",
        required=True,
        help="Reason for revocation",
    )
    
    # Override command
    override_parser = subparsers.add_parser("override", help="Set manual override (emergency only)")
    override_parser.add_argument(
        "--by",
        required=True,
        help="Name of person authorizing override",
    )
    override_parser.add_argument(
        "--reason",
        required=True,
        help="Reason for override",
    )
    override_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt",
    )
    
    # Clear override command
    clear_parser = subparsers.add_parser("clear-override", help="Clear manual override")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    if args.command == "status":
        return cmd_status(args)
    elif args.command == "approve":
        return cmd_approve(args)
    elif args.command == "revoke":
        return cmd_revoke(args)
    elif args.command == "override":
        return cmd_override(args)
    elif args.command == "clear-override":
        return cmd_clear_override(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
