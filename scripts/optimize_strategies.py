"""
Run strategy parameter optimization for all markets.

Usage:
    python scripts/optimize_strategies.py
    python scripts/optimize_strategies.py --market crypto --metric sharpe
    python scripts/optimize_strategies.py --days 60
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analytics.strategy_optimizer import StrategyOptimizer
from foundation.logger import get_logger

_log = get_logger("scripts", "optimize_strategies")


def main() -> None:
    parser = argparse.ArgumentParser(description="AAATS Strategy Optimizer")
    parser.add_argument("--market", choices=["crypto", "india", "all"], default="all")
    parser.add_argument("--metric", choices=["sharpe", "win_rate", "total_pnl"], default="sharpe",
                        help="Optimization objective")
    parser.add_argument("--days", type=int, default=30, help="Lookback period in days")
    parser.add_argument("--save", type=str, help="Save results to JSON file")
    args = parser.parse_args()

    markets = ["crypto", "india"] if args.market == "all" else [args.market]
    results = []

    for market in markets:
        print(f"\nOptimizing {market.upper()} (metric={args.metric}, lookback={args.days}d)...")
        opt = StrategyOptimizer(market=market, metric=args.metric, lookback_days=args.days)
        result = opt.optimize()
        results.append(result)

        print(f"\n{'=' * 50}")
        print(f"BEST PARAMS — {market.upper()}")
        print(f"{'=' * 50}")
        for k, v in result.params.items():
            print(f"  {k}: {v}")
        print(f"\nWin rate:    {result.win_rate:.2%}")
        print(f"Total PnL:   {result.total_pnl:,.2f}")
        print(f"Sharpe:      {result.sharpe_ratio:.2f}")
        print(f"Trades:      {result.total_trades}")

    if args.save:
        import dataclasses
        out = [dataclasses.asdict(r) for r in results]
        Path(args.save).write_text(json.dumps(out, indent=2))
        print(f"\nResults saved to {args.save}")


if __name__ == "__main__":
    main()
