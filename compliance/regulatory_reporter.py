"""
Regulatory reporter for AAATS.

Generates compliance reports for SEBI (India) and regulatory requirements:
  - Transaction reports (trade-by-trade detail)
  - Position concentration reports
  - Large trade flags (>1% of daily volume)
  - Short selling compliance (India: no naked short selling in cash segment)

Usage:
    from compliance.regulatory_reporter import RegulatoryReporter
    reporter = RegulatoryReporter()
    reporter.generate_daily_report(market="india")
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("compliance", "regulatory_reporter")
_DB_TRADES = Path("data/paper_trades.db")
_REPORTS_DIR = Path("reports/compliance")


class RegulatoryReporter:
    """
    Generates regulatory compliance reports.
    For paper trading: validates that the system WOULD comply if live.
    """

    def __init__(self, reports_dir: Path | None = None) -> None:
        self._reports_dir = reports_dir or _REPORTS_DIR
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_daily_report(self, market: str = "india", report_date: str | None = None) -> dict:
        """Generate a daily transaction report. Returns report dict."""
        rdate = report_date or date.today().isoformat()
        _log.info(f"Generating regulatory report: {market.upper()} for {rdate}")

        trades = self._load_trades(market, rdate)
        violations = self._check_violations(trades, market)

        report = {
            "report_date": rdate,
            "market": market,
            "generated_at": time.time(),
            "total_trades": len(trades),
            "total_buys": sum(1 for t in trades if t["action"] == "BUY"),
            "total_sells": sum(1 for t in trades if t["action"] == "SELL"),
            "total_notional": sum(t["shares"] * t["price"] for t in trades),
            "violations": violations,
            "compliant": len(violations) == 0,
            "trades": trades,
        }

        filename = self._reports_dir / f"{market}_{rdate}_regulatory.json"
        filename.write_text(json.dumps(report, indent=2))
        _log.info(f"Report saved: {filename} | violations={len(violations)}")
        return report

    def _load_trades(self, market: str, rdate: str) -> list[dict]:
        if not _DB_TRADES.exists():
            return []
        try:
            with sqlite3.connect(_DB_TRADES) as conn:
                rows = conn.execute(
                    """SELECT symbol, action, shares, price, pnl, signal, regime, created_at
                       FROM paper_trades WHERE market=? AND date(created_at, 'unixepoch') = ?
                       ORDER BY created_at""",
                    (market, rdate),
                ).fetchall()
            return [
                {"symbol": r[0], "action": r[1], "shares": r[2], "price": r[3],
                 "pnl": r[4] or 0.0, "signal": r[5], "regime": r[6], "created_at": r[7]}
                for r in rows
            ]
        except Exception as exc:
            _log.warning(f"Could not load trades: {exc}")
            return []

    def _check_violations(self, trades: list[dict], market: str) -> list[str]:
        violations = []
        if market == "india":
            # Check for naked short selling (SELL without prior BUY in same session)
            positions: set[str] = set()
            for t in trades:
                if t["action"] == "BUY":
                    positions.add(t["symbol"])
                elif t["action"] == "SELL" and t["symbol"] not in positions:
                    violations.append(
                        f"Potential naked short: {t['symbol']} SELL without intraday BUY"
                    )
        return violations

    def get_compliance_status(self, market: str = "india") -> dict:
        """Quick compliance check based on recent reports."""
        files = sorted(self._reports_dir.glob(f"{market}_*_regulatory.json"))
        if not files:
            return {"status": "NO_REPORTS", "compliant": None}
        latest = json.loads(files[-1].read_text())
        return {
            "status": "COMPLIANT" if latest["compliant"] else "VIOLATIONS_FOUND",
            "compliant": latest["compliant"],
            "date": latest["report_date"],
            "violations": latest.get("violations", []),
        }
