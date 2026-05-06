"""
Run stress tests against current portfolio positions.

Usage:
    python scripts/run_stress_tests.py
    python scripts/run_stress_tests.py --market crypto --capital 10000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.position_manager import PersistentPositionManager
from analytics.stress_tester import StressTester
from foundation.logger import get_logger

_log = get_logger("scripts", "run_stress_tests")


def main() -> None:
    parser = argparse.ArgumentParser(description="AAATS Stress Tests")
    parser.add_argument("--market", choices=["crypto", "india", "all"], default="all")
    parser.add_argument("--capital", type=float, default=500_000.0, help="Portfolio capital")
    parser.add_argument("--save", action="store_true", help="Save report to reports/")
    args = parser.parse_args()

    markets = ["crypto", "india"] if args.market == "all" else [args.market]
    all_positions = []
    for market in markets:
        pm = PersistentPositionManager(market=market)
        all_positions.extend(pm.get_open_positions())

    print(f"\nOpen positions: {len(all_positions)}")
    if not all_positions:
        print("No open positions — stress testing with hypothetical 100% capital exposure.")
        all_positions = [{"symbol": "PORTFOLIO", "entry_price": args.capital, "shares": 1.0}]

    st = StressTester(capital=args.capital)
    results = st.run_all_scenarios(all_positions)
    st.print_report(results)

    if args.save:
        path = st.save_report(results)
        print(f"\nReport saved: {path}")

    # Summary
    failed = [r for r in results if not r.survivable]
    if failed:
        print(f"\n⚠️  {len(failed)} scenario(s) would be CATASTROPHIC:")
        for r in failed:
            print(f"   • {r.description} ({r.market_drop:.0%})")
    else:
        print("\n✅ Portfolio survives all standard stress scenarios.")


if __name__ == "__main__":
    main()
