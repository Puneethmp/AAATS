"""
AAATS Emergency Kill Switch CLI.

Lives at the repo root deliberately. README.md documents the canonical
invocation as `python kill.py --market <market>` from the project root, and
foundation/kill_switch.py identifies callers as "kill.py CLI". Moving this
under tools/ would break the operator's muscle-memory invocation during an
incident — not worth the symmetry win.

Usage:
    python kill.py --market us
    python kill.py --market india
    python kill.py --market crypto
    python kill.py --market all --confirm
    python kill.py --reset --market us --authorized-by Puneeth --reason "Issue resolved"
"""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AAATS Emergency Kill Switch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Halt US trading:        python kill.py --market us
  Halt India + F&O:       python kill.py --market india
  Halt everything:        python kill.py --market all --confirm
  Resume US trading:      python kill.py --reset --market us --authorized-by Puneeth --reason "Fixed"
        """,
    )

    parser.add_argument(
        "--market",
        choices=["us", "india", "crypto", "all"],
        required=True,
        help="Market to halt or reset.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required safety flag when halting ALL markets.",
    )
    parser.add_argument(
        "--reason",
        default="Manual kill switch activation via CLI",
        help="Reason for halt (written to audit trail).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset (resume) a halted market instead of halting it.",
    )
    parser.add_argument(
        "--authorized-by",
        dest="authorized_by",
        default="",
        help="Required with --reset: name of the person authorising the reset.",
    )

    args = parser.parse_args()

    if args.reset:
        if not args.authorized_by:
            print("ERROR: --authorized-by is required when using --reset.")
            print("Example: python kill.py --reset --market us --authorized-by Puneeth --reason 'Fixed'")
            sys.exit(1)

        from foundation.kill_switch import reset

        reset(market=args.market, authorized_by=args.authorized_by, reason=args.reason)
        print(f"RESUME: trading resumed for market '{args.market}'.")
        print(f"  Authorized by: {args.authorized_by}")
        print(f"  Reason: {args.reason}")
        print("  Event written to audit trail.")
        return

    # ── Halt path ─────────────────────────────────────────────
    if args.market == "all" and not args.confirm:
        print("ERROR: --confirm flag is required when halting ALL markets.")
        print("This is a safety gate to prevent accidental full system halt.")
        print("Usage: python kill.py --market all --confirm")
        sys.exit(1)

    from foundation.kill_switch import halt

    halt(market=args.market, reason=args.reason, triggered_by="kill.py CLI")

    print(f"HALTED: market '{args.market}' is now halted.")
    print(f"  Reason: {args.reason}")
    print("  State persisted to data/halt_state.json (survives restart).")
    print("  Telegram alert sent.")
    print(f"  To resume: python kill.py --reset --market {args.market} --authorized-by <name> --reason <reason>")


if __name__ == "__main__":
    main()
