"""
Tax optimizer for AAATS (India tax rules).

Tracks:
  - Short-term capital gains (STCG): equity held < 12 months → 20% tax (post-July 2024 budget)
  - Long-term capital gains (LTCG): equity held ≥ 12 months → 12.5% above ₹1.25L
  - Securities Transaction Tax (STT): 0.1% on delivery, 0.025% on intraday
  - Crypto: treated as VDA (Virtual Digital Asset), flat 30% + 1% TDS

Usage:
    from compliance.tax_optimizer import TaxOptimizer
    to = TaxOptimizer()
    tax = to.estimate_tax(market="india", pnl=50000.0, holding_days=180)
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("compliance", "tax_optimizer")
_DB = Path("data/tax_records.db")


@dataclass
class TaxEstimate:
    market: str
    pnl: float
    holding_days: int
    tax_type: str        # "STCG", "LTCG", "VDA", "INTRADAY"
    tax_rate: float
    tax_amount: float
    stt: float
    net_after_tax: float


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tax_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            pnl REAL NOT NULL,
            holding_days INTEGER NOT NULL,
            tax_type TEXT NOT NULL,
            tax_amount REAL NOT NULL,
            stt REAL NOT NULL,
            trade_date TEXT NOT NULL,
            recorded_at REAL NOT NULL
        )
    """)
    conn.commit()


class TaxOptimizer:
    """
    Estimates and records tax liability for trades.
    Tax rates based on India Budget 2024 (effective July 23, 2024).
    """

    # India equity tax rates (post-Budget 2024)
    _STCG_RATE = 0.20       # Short-term: 20% on equity gains < 12 months
    _LTCG_RATE = 0.125      # Long-term: 12.5% on equity gains ≥ 12 months (above ₹1.25L)
    _LTCG_EXEMPTION = 125_000.0  # ₹1.25L LTCG exemption per year
    _INTRADAY_RATE = 0.30   # Intraday treated as business income ~30% bracket
    _STT_DELIVERY = 0.001   # 0.1% STT on delivery
    _STT_INTRADAY = 0.00025  # 0.025% STT on intraday

    # Crypto (VDA) tax rates
    _VDA_RATE = 0.30        # Flat 30% on VDA profits
    _VDA_TDS = 0.01         # 1% TDS deducted at source

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def estimate_tax(
        self,
        market: str,
        pnl: float,
        holding_days: int,
        notional: float = 0.0,
        symbol: str = "PORTFOLIO",
        intraday: bool = False,
    ) -> TaxEstimate:
        """Estimate tax for a trade. For paper trading — shows WOULD-BE tax."""
        if market == "crypto":
            tax_type = "VDA"
            tax_rate = self._VDA_RATE if pnl > 0 else 0.0
            stt = 0.0
            tax_amount = max(0.0, pnl) * tax_rate
        elif market == "india":
            if intraday:
                tax_type = "INTRADAY"
                tax_rate = self._INTRADAY_RATE
                stt = notional * self._STT_INTRADAY
            elif holding_days < 365:
                tax_type = "STCG"
                tax_rate = self._STCG_RATE
                stt = notional * self._STT_DELIVERY
            else:
                tax_type = "LTCG"
                tax_rate = self._LTCG_RATE
                stt = notional * self._STT_DELIVERY
            tax_amount = max(0.0, pnl) * tax_rate if pnl > 0 else 0.0
        else:
            tax_type = "UNKNOWN"
            tax_rate = 0.0
            stt = 0.0
            tax_amount = 0.0

        net = pnl - tax_amount - stt
        estimate = TaxEstimate(
            market=market, pnl=round(pnl, 2), holding_days=holding_days,
            tax_type=tax_type, tax_rate=tax_rate,
            tax_amount=round(tax_amount, 2), stt=round(stt, 2),
            net_after_tax=round(net, 2),
        )
        self._record(symbol, estimate)
        return estimate

    def _record(self, symbol: str, est: TaxEstimate) -> None:
        from datetime import date
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT INTO tax_records (market, symbol, pnl, holding_days, tax_type, tax_amount, stt, trade_date, recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (est.market, symbol, est.pnl, est.holding_days, est.tax_type,
                 est.tax_amount, est.stt, date.today().isoformat(), time.time()),
            )

    def annual_tax_summary(self, year: int | None = None) -> dict:
        """Return annual tax liability summary."""
        from datetime import date
        yr = year or date.today().year
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                """SELECT market, tax_type, SUM(pnl), SUM(tax_amount), SUM(stt), COUNT(*)
                   FROM tax_records WHERE trade_date LIKE ?
                   GROUP BY market, tax_type""",
                (f"{yr}%",),
            ).fetchall()
        result = {}
        for r in rows:
            key = f"{r[0]}_{r[1]}"
            result[key] = {
                "total_pnl": round(r[2] or 0, 2),
                "total_tax": round(r[3] or 0, 2),
                "total_stt": round(r[4] or 0, 2),
                "trades": r[5],
            }
        return result
