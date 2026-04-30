"""
Drawdown monitor for AAATS.

Tracks equity curve per market, measures peak-to-trough drawdown,
and triggers a kill switch halt when threshold is breached.

Usage:
    from risk.drawdown_monitor import DrawdownMonitor
    dm = DrawdownMonitor(market="crypto", halt_threshold=0.15)
    dm.update(current_equity=95000.0)  # halts if -15% from peak
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from foundation.logger import get_logger
from foundation.kill_switch import halt

_log = get_logger("risk", "drawdown_monitor")
_DB = Path("data/equity_curve.db")


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equity_curve (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            equity REAL NOT NULL,
            peak REAL NOT NULL,
            current_drawdown REAL NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.commit()


class DrawdownMonitor:
    """
    Tracks equity and triggers kill switch when max drawdown is breached.

    Args:
        market:          Market identifier ("crypto", "india").
        initial_equity:  Starting capital.
        halt_threshold:  Drawdown fraction that triggers halt (default 0.15 = 15%).
        daily_loss_limit: Max daily loss fraction (default 0.05 = 5%).
    """

    def __init__(
        self,
        market: str,
        initial_equity: float = 100_000.0,
        halt_threshold: float = 0.15,
        daily_loss_limit: float = 0.05,
    ) -> None:
        self._market = market
        self._peak = initial_equity
        self._halt_threshold = halt_threshold
        self._daily_loss_limit = daily_loss_limit
        self._daily_start = initial_equity
        self._day_start_ts = time.time()
        _DB.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(_DB) as conn:
            _init_db(conn)

    def update(self, current_equity: float) -> float:
        """
        Record current equity, compute drawdown, halt if threshold breached.
        Returns current drawdown fraction (0.0 = no drawdown, 0.15 = -15%).
        """
        # Update peak
        if current_equity > self._peak:
            self._peak = current_equity

        drawdown = (self._peak - current_equity) / max(self._peak, 1e-9)
        now = time.time()

        # Log to DB
        with sqlite3.connect(_DB) as conn:
            conn.execute(
                "INSERT INTO equity_curve (market, equity, peak, current_drawdown, timestamp) VALUES (?,?,?,?,?)",
                (self._market, current_equity, self._peak, drawdown, now),
            )

        # Reset daily tracking at midnight
        if now - self._day_start_ts > 86400:
            self._daily_start = current_equity
            self._day_start_ts = now

        daily_loss = (self._daily_start - current_equity) / max(self._daily_start, 1e-9)

        if drawdown >= self._halt_threshold:
            _log.critical(
                f"MAX DRAWDOWN BREACHED: {self._market} | drawdown={drawdown:.2%} >= {self._halt_threshold:.2%}"
            )
            halt(
                market=self._market,
                reason=f"Max drawdown breached: {drawdown:.2%} (limit: {self._halt_threshold:.2%})",
                triggered_by="drawdown_monitor",
            )

        elif daily_loss >= self._daily_loss_limit:
            _log.critical(
                f"DAILY LOSS LIMIT BREACHED: {self._market} | daily_loss={daily_loss:.2%}"
            )
            halt(
                market=self._market,
                reason=f"Daily loss limit breached: {daily_loss:.2%} (limit: {self._daily_loss_limit:.2%})",
                triggered_by="drawdown_monitor",
            )

        elif drawdown > 0.05:
            _log.warning(f"Drawdown warning: {self._market} | {drawdown:.2%} from peak {self._peak:.0f}")

        return drawdown

    def get_max_drawdown(self) -> float:
        """Return the all-time max drawdown for this market."""
        with sqlite3.connect(_DB) as conn:
            row = conn.execute(
                "SELECT MAX(current_drawdown) FROM equity_curve WHERE market=?",
                (self._market,),
            ).fetchone()
        return row[0] or 0.0
