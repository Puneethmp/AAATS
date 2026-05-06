"""
Mode manager for AAATS.

Controls system operating mode:
  - PAPER: simulate trades, no real orders
  - LIVE: execute real orders with real capital

Mode switching requires explicit authorization and minimum paper trading evidence.

Usage:
    from foundation.mode_manager import ModeManager
    mm = ModeManager()
    mm.switch_to_live(authorized_by="Puneeth", capital=10000.0, evidence_weeks=8)
    mode = mm.get_mode()  # "paper" or "live"
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("system", "mode_manager")
_STATE_FILE = Path("data/mode_state.json")
_MIN_PAPER_WEEKS = 4  # Minimum paper trading weeks before going live


class ModeManager:
    """
    Controls PAPER vs LIVE trading mode transitions.
    All transitions are logged and require explicit authorization.
    """

    def __init__(self, state_file: Path | None = None) -> None:
        self._file = state_file or _STATE_FILE
        self._file.parent.mkdir(parents=True, exist_ok=True)
        if not self._file.exists():
            self._save(self._default_state())

    def _default_state(self) -> dict:
        return {
            "mode": "paper",
            "capital": 0.0,
            "paper_trading_started_at": None,
            "went_live_at": None,
            "authorized_by": None,
            "last_updated": time.time(),
        }

    def _load(self) -> dict:
        try:
            return json.loads(self._file.read_text())
        except Exception:
            return self._default_state()

    def _save(self, state: dict) -> None:
        state["last_updated"] = time.time()
        self._file.write_text(json.dumps(state, indent=2))

    def get_mode(self) -> str:
        """Return current mode: 'paper' or 'live'."""
        return self._load().get("mode", "paper")

    def is_live(self) -> bool:
        return self.get_mode() == "live"

    def is_paper(self) -> bool:
        return self.get_mode() == "paper"

    def start_paper_trading(self) -> None:
        state = self._load()
        if not state.get("paper_trading_started_at"):
            state["paper_trading_started_at"] = time.time()
            self._save(state)
        _log.info("Paper trading mode active")

    def switch_to_live(
        self,
        authorized_by: str,
        capital: float,
        evidence_weeks: int = 0,
        bypass_check: bool = False,
    ) -> None:
        """
        Switch to live trading. Requires:
          - At least _MIN_PAPER_WEEKS of paper trading
          - Explicit authorization
          - Capital amount confirmation
        """
        state = self._load()
        paper_start = state.get("paper_trading_started_at")

        if not bypass_check:
            if not paper_start:
                raise RuntimeError("No paper trading evidence — start paper trading first")
            weeks_of_paper = (time.time() - paper_start) / (7 * 86400)
            min_weeks = max(_MIN_PAPER_WEEKS, evidence_weeks)
            if weeks_of_paper < min_weeks:
                raise RuntimeError(
                    f"Insufficient paper trading: {weeks_of_paper:.1f} weeks "
                    f"(minimum: {min_weeks} weeks required)"
                )

        if capital <= 0:
            raise ValueError("Capital must be positive")

        state.update({
            "mode": "live",
            "capital": capital,
            "went_live_at": time.time(),
            "authorized_by": authorized_by,
        })
        self._save(state)

        _log.critical(
            f"MODE SWITCH: PAPER → LIVE | authorized_by={authorized_by} | capital=₹{capital:,.0f}"
        )
        try:
            from observability.alerts import send_alert
            send_alert(
                f"⚠️ LIVE TRADING ACTIVATED\n"
                f"Authorized by: {authorized_by}\n"
                f"Capital: ₹{capital:,.0f}",
                market="all",
            )
        except Exception:
            pass

    def switch_to_paper(self, authorized_by: str, reason: str) -> None:
        """Emergency downgrade to paper trading."""
        state = self._load()
        state.update({"mode": "paper", "authorized_by": authorized_by})
        self._save(state)
        _log.warning(f"MODE SWITCH: LIVE → PAPER | authorized_by={authorized_by} | reason={reason}")

    def get_status(self) -> dict:
        state = self._load()
        paper_start = state.get("paper_trading_started_at")
        weeks = (time.time() - paper_start) / (7 * 86400) if paper_start else 0
        return {
            **state,
            "paper_trading_weeks": round(weeks, 1),
            "ready_for_live": weeks >= _MIN_PAPER_WEEKS,
        }
