"""
Funding rate monitor for Binance perpetual futures.

Monitors 8-hourly funding rates and warns when rates become extreme,
avoiding positions where funding costs erode profitability.

Usage:
    from risk.funding_monitor import FundingMonitor
    fm = FundingMonitor()
    should_hold = fm.check_funding_rates(["BTC/USDT:USDT", "ETH/USDT:USDT"])
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("risk", "funding_monitor")
_DB = Path("data/funding_rates.db")
_WARN_THRESHOLD = 0.001    # 0.1% per 8h = extreme
_AVOID_THRESHOLD = 0.003   # 0.3% per 8h = avoid long


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS funding_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            rate REAL NOT NULL,
            funding_time REAL NOT NULL,
            recorded_at REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fund_sym ON funding_rates(symbol, recorded_at)")
    conn.commit()


class FundingMonitor:
    """
    Monitors Binance perpetual futures funding rates.
    Warns on extreme rates, can block new longs when funding is very expensive.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)

    def check_funding_rates(self, symbols: list[str]) -> dict[str, float]:
        """
        Fetch and record current funding rates for perpetual symbols.
        Returns {symbol: rate} dict. Rate > _AVOID_THRESHOLD means avoid new longs.
        """
        rates: dict[str, float] = {}
        try:
            import ccxt
            exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
            for symbol in symbols:
                try:
                    info = exchange.fetch_funding_rate(symbol)
                    rate = float(info.get("fundingRate", 0.0))
                    rates[symbol] = rate
                    self._record(symbol, rate, info.get("fundingDatetime", time.time()))
                    if abs(rate) >= _AVOID_THRESHOLD:
                        _log.warning(f"HIGH FUNDING RATE: {symbol} = {rate:.4%} — avoid new longs")
                    elif abs(rate) >= _WARN_THRESHOLD:
                        _log.info(f"Elevated funding: {symbol} = {rate:.4%}")
                except Exception as exc:
                    _log.debug(f"Funding rate not available for {symbol}: {exc}")
        except ImportError:
            _log.debug("ccxt not available for funding rate check")
        except Exception as exc:
            _log.error(f"Funding rate fetch failed: {exc}")
        return rates

    def _record(self, symbol: str, rate: float, funding_time) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT INTO funding_rates (symbol, rate, funding_time, recorded_at) VALUES (?,?,?,?)",
                (symbol, rate, float(funding_time) if isinstance(funding_time, (int, float)) else time.time(), time.time()),
            )

    def should_avoid_long(self, symbol: str) -> bool:
        """Return True if funding rate is high enough to avoid new long positions."""
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT rate FROM funding_rates WHERE symbol=? ORDER BY recorded_at DESC LIMIT 1",
                (symbol,),
            ).fetchone()
        if row and row[0] >= _AVOID_THRESHOLD:
            return True
        return False

    def get_latest_rates(self, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute(
                """SELECT symbol, rate, recorded_at FROM funding_rates
                   WHERE recorded_at > ? ORDER BY recorded_at DESC LIMIT ?""",
                (time.time() - 86400, limit),
            ).fetchall()
        return [{"symbol": r[0], "rate": r[1], "recorded_at": r[2]} for r in rows]
