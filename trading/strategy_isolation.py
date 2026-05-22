"""
Per-strategy exception isolation (Phase D.1).

Closes catalog row 2: previously, a strategy raising mid-cycle would log
but the existing per-strategy try/except in live_paper_runner.py left
operators blind to the silent recurrence. The runner already isolates
exceptions per-strategy; what was missing is:

  1. A Prometheus counter incremented on every exception, labelled by
     strategy_id. Surfaced by monitoring/metrics_exporter via
     data/strategy_exception_state.json.
  2. Consecutive-exception tracking. Three in a row → auto-halt that
     strategy alone (via risk/strategy_halt.halt_strategy), NOT the
     whole market.
  3. A Telegram alert at halt time, gated by foundation/kill_switch's
     alert sender so the existing observability rules apply.

This module is intentionally a thin helper that the existing 5
try/except call sites in trading/live_paper_runner.py call into.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from foundation.logger import get_logger
from risk.strategy_halt import halt_strategy, is_strategy_halted

_log = get_logger("trading", "strategy_isolation")

# Counter + consecutive-exception state lives on disk so the
# metrics_exporter (separate process / container) can scrape it and so a
# container restart does not lose the consecutive-exception count
# mid-streak.
STATE_FILE = Path(
    os.environ.get(
        "AAATS_STRATEGY_EXCEPTION_FILE",
        str(Path(os.environ.get("AAATS_DATA", "data")) / "strategy_exception_state.json"),
    )
)

# Auto-halt threshold. Three consecutive failures of the same strategy is
# the failure-mode-catalog row 2 default; cleared on first successful run.
CONSECUTIVE_HALT_THRESHOLD = 3

T = TypeVar("T")


def _load_state() -> dict[str, dict[str, Any]]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("strategy_exception_state.json unreadable (%s); resetting", exc)
        return {}


def _save_state(state: dict[str, dict[str, Any]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _record_exception(strategy_id: str, exc: BaseException) -> int:
    """Increment counters for a strategy exception. Returns the new
    consecutive-exception count."""
    state = _load_state()
    entry = state.get(strategy_id, {})
    entry["total_exceptions"] = int(entry.get("total_exceptions", 0)) + 1
    entry["consecutive_exceptions"] = int(entry.get("consecutive_exceptions", 0)) + 1
    entry["last_exception"] = repr(exc)
    entry["last_exception_at"] = datetime.now(timezone.utc).isoformat()
    state[strategy_id] = entry
    _save_state(state)
    return int(entry["consecutive_exceptions"])


def _record_success(strategy_id: str) -> None:
    """Mark a successful run — clears the consecutive-exception streak."""
    state = _load_state()
    entry = state.get(strategy_id, {})
    if int(entry.get("consecutive_exceptions", 0)) == 0:
        return  # No-op fast path; avoid disk write on every clean cycle.
    entry["consecutive_exceptions"] = 0
    entry["last_success_at"] = datetime.now(timezone.utc).isoformat()
    state[strategy_id] = entry
    _save_state(state)


def _send_halt_alert(strategy_id: str, consec: int, exc: BaseException) -> None:
    """Best-effort Telegram alert when auto-halt fires."""
    try:
        from observability.alerts import send_alert
        send_alert(
            (f"STRATEGY AUTO-HALT\n"
             f"Strategy: {strategy_id}\n"
             f"Reason: {consec} consecutive cycle exceptions\n"
             f"Last exception: {exc!r}"),
            market="crypto",
        )
    except Exception as alert_exc:
        _log.error(
            "send_alert failed during strategy auto-halt for %s: %s",
            strategy_id, alert_exc,
        )


def run_strategy_with_isolation(
    strategy_id: str,
    func: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T | None:
    """Execute ``func(*args, **kwargs)`` inside an isolation envelope.

    Behaviour:
      - If strategy is already halted (data/strategy_halt_state.json):
        log debug, return None, do NOT call func.
      - Otherwise call func. On success: clear the consecutive-exception
        streak. On exception: log with strategy_id, increment the
        per-strategy counter on disk, return None to the caller so the
        cycle continues with the next strategy.
      - When consecutive_exceptions hits CONSECUTIVE_HALT_THRESHOLD,
        invoke risk.strategy_halt.halt_strategy and best-effort Telegram
        alert.

    Returns the function's result on success, or None on exception or
    pre-existing halt. Callers that need to distinguish must check
    is_strategy_halted(strategy_id) themselves.
    """
    if is_strategy_halted(strategy_id):
        _log.debug("strategy %s currently halted; skipping dispatch", strategy_id)
        return None

    try:
        result = func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — broad catch is the point of isolation
        consec = _record_exception(strategy_id, exc)
        _log.error(
            "strategy %s raised (#%d consecutive): %s",
            strategy_id, consec, exc, exc_info=True,
        )
        if consec >= CONSECUTIVE_HALT_THRESHOLD:
            halt_strategy(
                strategy_id,
                reason=f"{consec} consecutive cycle exceptions",
                consecutive_exceptions=consec,
            )
            _send_halt_alert(strategy_id, consec, exc)
        return None

    _record_success(strategy_id)
    return result
