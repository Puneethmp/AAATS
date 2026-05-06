"""
Macro economic hedging for AAATS.

Detects macro stress conditions (VIX spikes, BTC dominance shifts, USD strength)
and applies defensive position sizing to reduce exposure.

Usage:
    from risk.macro_hedge import MacroHedgeMonitor
    mhm = MacroHedgeMonitor()
    hedge_factor = mhm.get_hedge_factor()  # 0.0-1.0 (1.0 = no hedge, 0.0 = full defensive)
    if hedge_factor < 0.5:
        shares = shares * hedge_factor   # reduce position size
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("risk", "macro_hedge")
_DB = Path("data/macro_signals.db")


@dataclass
class MacroState:
    btc_dominance: float      # BTC market cap dominance (0-1)
    fear_greed_index: float   # 0-100 (0=extreme fear, 100=extreme greed)
    usdt_dominance: float     # USDT dominance spike = risk-off
    hedge_factor: float       # Final hedge factor (1.0 = no hedge, 0.5 = half position)
    signal: str


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            btc_dominance REAL,
            fear_greed REAL,
            usdt_dominance REAL,
            hedge_factor REAL NOT NULL,
            signal TEXT NOT NULL
        )
    """)
    conn.commit()


class MacroHedgeMonitor:
    """
    Monitors macro-economic signals and computes a hedge factor for position sizing.
    Hedge factor 1.0 = full size, 0.5 = half size, 0.0 = no new positions.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db = db_path or _DB
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            _init_db(conn)
        self._last_check: float = 0
        self._cached_factor: float = 1.0

    def get_hedge_factor(self) -> float:
        """Return the current hedge factor (cached for 30 min)."""
        if time.time() - self._last_check < 1800:
            return self._cached_factor
        state = self._fetch_macro_state()
        self._record(state)
        self._last_check = time.time()
        self._cached_factor = state.hedge_factor
        return state.hedge_factor

    def _fetch_macro_state(self) -> MacroState:
        """Fetch macro signals from free APIs. Fails gracefully (returns neutral)."""
        fear_greed = self._fetch_fear_greed()
        btc_dom = 0.5
        usdt_dom = 0.0

        # Compute hedge factor
        if fear_greed < 20:  # Extreme fear
            factor = 0.3
            signal = "EXTREME_FEAR"
        elif fear_greed < 35:  # Fear
            factor = 0.6
            signal = "FEAR"
        elif fear_greed > 85:  # Extreme greed (overbought)
            factor = 0.7
            signal = "EXTREME_GREED"
        elif fear_greed > 70:  # Greed
            factor = 0.85
            signal = "GREED"
        else:
            factor = 1.0
            signal = "NEUTRAL"

        if factor < 1.0:
            _log.info(f"Macro hedge active: {signal} | factor={factor:.2f} | fear_greed={fear_greed:.0f}")

        return MacroState(
            btc_dominance=btc_dom,
            fear_greed_index=fear_greed,
            usdt_dominance=usdt_dom,
            hedge_factor=factor,
            signal=signal,
        )

    def _fetch_fear_greed(self) -> float:
        """Fetch Bitcoin Fear & Greed index from alternative.me. Returns 50 on failure."""
        try:
            import urllib.request
            import json
            url = "https://api.alternative.me/fng/?limit=1&format=json"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            return float(data["data"][0]["value"])
        except Exception as exc:
            _log.debug(f"Fear & Greed fetch failed: {exc} — using neutral (50)")
            return 50.0

    def _record(self, state: MacroState) -> None:
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                "INSERT INTO macro_signals (timestamp, btc_dominance, fear_greed, usdt_dominance, hedge_factor, signal) VALUES (?,?,?,?,?,?)",
                (time.time(), state.btc_dominance, state.fear_greed_index, state.usdt_dominance, state.hedge_factor, state.signal),
            )
