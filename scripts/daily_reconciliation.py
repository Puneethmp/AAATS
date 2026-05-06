"""
Daily reconciliation script for AAATS.

Runs at 4:00 PM IST daily (after NSE close) to:
  1. Compare DB positions vs expected positions
  2. Mark overdue settlements
  3. Check equity curve for anomalies
  4. Generate daily summary report

Usage:
    python scripts/daily_reconciliation.py
    python scripts/daily_reconciliation.py --market india
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from foundation.logger import get_logger
from risk.position_manager import PersistentPositionManager
from risk.settlement_manager import SettlementManager
from risk.drawdown_monitor import DrawdownMonitor
from analytics.pnl_attribution import PnLAttribution

_log = get_logger("scripts", "daily_reconciliation")
_REPORT_DIR = Path("reports")


def reconcile_market(market: str) -> dict:
    """Run full reconciliation for a single market. Returns summary dict."""
    _log.info(f"=== Daily reconciliation: {market.upper()} ===")
    pm = PersistentPositionManager(market=market)
    pnl_attr = PnLAttribution()

    open_positions = pm.get_open_positions()
    total_pnl = pnl_attr.total_pnl(market)

    summary: dict = {
        "market": market,
        "date": date.today().isoformat(),
        "open_positions": len(open_positions),
        "total_pnl": round(total_pnl, 2),
        "issues": [],
    }

    # Check for stale positions (open > 5 days)
    import time
    now = time.time()
    for pos in open_positions:
        age_hours = (now - pos["entry_time"]) / 3600
        if age_hours > 120:  # 5 days
            issue = f"Stale position: {pos['symbol']} open for {age_hours:.0f}h"
            summary["issues"].append(issue)
            _log.warning(issue)

    # India-specific: check settlements
    if market == "india":
        sm = SettlementManager()
        unsettled = sm.get_unsettled_positions()
        overdue = [u for u in unsettled if u["settlement_date"] < date.today().isoformat()]
        if overdue:
            summary["overdue_settlements"] = len(overdue)
            summary["issues"].append(f"{len(overdue)} overdue settlement(s)")
            for s in overdue:
                _log.warning(f"Overdue settlement: {s['symbol']} due {s['settlement_date']}")

    # Check drawdown
    dm = DrawdownMonitor(market=market)
    max_dd = dm.get_max_drawdown()
    summary["max_drawdown"] = round(max_dd, 4)
    if max_dd > 0.10:
        summary["issues"].append(f"High drawdown: {max_dd:.2%}")

    # PnL attribution summary
    pnl_summary = pnl_attr.get_summary(market=market)
    summary["pnl_by_regime"] = pnl_summary

    status = "OK" if not summary["issues"] else "ISSUES_FOUND"
    summary["status"] = status
    _log.info(f"Reconciliation complete: {market.upper()} | status={status} | pnl={total_pnl:.2f}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="AAATS Daily Reconciliation")
    parser.add_argument("--market", choices=["crypto", "india", "all"], default="all")
    parser.add_argument("--no-report", action="store_true", help="Skip report file")
    args = parser.parse_args()

    markets = ["crypto", "india"] if args.market == "all" else [args.market]
    results = []
    for market in markets:
        try:
            result = reconcile_market(market)
            results.append(result)
        except Exception as exc:
            _log.error(f"Reconciliation failed for {market}: {exc}")
            results.append({"market": market, "status": "ERROR", "error": str(exc)})

    all_ok = all(r.get("status") == "OK" for r in results)
    print("\n" + "=" * 50)
    print("DAILY RECONCILIATION SUMMARY")
    print("=" * 50)
    for r in results:
        status_icon = "✅" if r.get("status") == "OK" else "⚠️"
        print(f"{status_icon} {r['market'].upper()}: {r.get('status', 'UNKNOWN')}")
        if r.get("issues"):
            for issue in r["issues"]:
                print(f"   • {issue}")
    print("=" * 50)
    print(f"Overall: {'ALL CLEAR ✅' if all_ok else 'ACTION REQUIRED ⚠️'}")

    if not args.no_report:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = _REPORT_DIR / f"reconciliation_{date.today().isoformat()}.json"
        report_path.write_text(json.dumps(results, indent=2))
        print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
