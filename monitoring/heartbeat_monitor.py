"""
Heartbeat Monitor — reader for ``data/heartbeat.json`` (FLAT schema).

The trading runner (``trading/live_paper_runner.py:1899-1904``) writes the
canonical flat shape directly each cycle::

    {"timestamp": "<iso>", "cycle": <int>, "market": "<name>",
     "cycle_duration_seconds": <float>}

This module is now a read-only wrapper. The legacy
``HeartbeatMonitor.emit_heartbeat`` path (which wrote a nested per-market
dict) was removed 2026-05-22 as part of catalog row 1 cleanup; the flat
shape is canonical and is the only thing this module knows how to read.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("monitoring", "heartbeat_monitor")


@dataclass
class Heartbeat:
    """Single heartbeat record (FLAT schema, mirrors ``state.schemas.HeartbeatSchema``)."""

    timestamp: str
    cycle: int
    market: str
    cycle_duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class HeartbeatMonitor:
    """Reads ``data/heartbeat.json`` written by the runner."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path = self.data_dir / "heartbeat.json"

    def _read_raw(self) -> dict | None:
        try:
            if not self.heartbeat_path.exists():
                return None
            data = json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return data
        except Exception as e:
            _log.error(f"Failed to read heartbeat: {e}")
            return None

    @staticmethod
    def _from_raw(data: dict) -> Heartbeat | None:
        try:
            return Heartbeat(
                timestamp=str(data["timestamp"]),
                cycle=int(data.get("cycle", 0)),
                market=str(data["market"]),
                cycle_duration_seconds=float(
                    data.get("cycle_duration_seconds", 0.0)
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None

    # "both" mode (crypto+india) fans out per-market — see _BOTH_FANOUT.
    _BOTH_FANOUT: frozenset[str] = frozenset({"crypto", "india"})

    def get_heartbeat(self, market: str) -> Heartbeat | None:
        """Return the latest heartbeat if it belongs to ``market``, else ``None``."""
        data = self._read_raw()
        if not data:
            return None
        hb = self._from_raw(data)
        if hb is None:
            return None
        if hb.market == market:
            return hb
        if hb.market == "both" and market in self._BOTH_FANOUT:
            return hb
        return None

    def get_all_heartbeats(self) -> dict[str, Heartbeat]:
        """
        Return ``{market -> latest Heartbeat}``.

        The flat schema holds exactly one heartbeat (for whichever market
        the runner is configured to drive). If the runner is in
        ``--market both`` mode the single heartbeat is attributed to both
        ``crypto`` and ``india`` so per-market freshness consumers keep
        working.
        """
        data = self._read_raw()
        if not data:
            return {}
        hb = self._from_raw(data)
        if hb is None:
            return {}
        if hb.market == "both":
            return {"crypto": hb, "india": hb}
        return {hb.market: hb}

    def is_alive(self, market: str, max_age_seconds: float = 120.0) -> bool:
        """True iff the latest heartbeat belongs to ``market`` and is fresh."""
        hb = self.get_heartbeat(market)
        if hb is None:
            return False
        try:
            hb_time = datetime.fromisoformat(hb.timestamp)
            if hb_time.tzinfo is None:
                hb_time = hb_time.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - hb_time).total_seconds()
            return age < max_age_seconds
        except Exception:
            return False


_monitor = HeartbeatMonitor()


def get_heartbeat(market: str) -> Heartbeat | None:
    return _monitor.get_heartbeat(market)


def get_all_heartbeats() -> dict[str, Heartbeat]:
    return _monitor.get_all_heartbeats()


def is_alive(market: str, max_age_seconds: float = 120.0) -> bool:
    return _monitor.is_alive(market, max_age_seconds)
