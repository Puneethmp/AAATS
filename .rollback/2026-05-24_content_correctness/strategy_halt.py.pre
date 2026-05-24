"""
Per-strategy halt state (Phase D.1).

Distinct from foundation/kill_switch.py's per-market halt: this module
tracks halts at the **strategy** granularity so that a single misbehaving
strategy can be taken out of the cycle without halting its sibling
strategies. Used by trading/strategy_isolation.py to auto-halt a strategy
after 3 consecutive cycle-exceptions.

State persists to data/strategy_halt_state.json:
    {
        "C1_stat_arb":         {"halted": false},
        "C3_altcoin_reversion": {"halted": true,
                                  "reason": "3 consecutive cycle exceptions",
                                  "halted_at": "2026-05-22T04:01:23Z",
                                  "consecutive_exceptions": 3}
    }

Survives container restart so a halt does NOT silently reset on the next
boot.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from foundation.logger import get_logger

_log = get_logger("risk", "strategy_halt")

STRATEGY_HALT_FILE = Path(
    os.environ.get(
        "AAATS_STRATEGY_HALT_FILE",
        str(Path(os.environ.get("AAATS_DATA", "data")) / "strategy_halt_state.json"),
    )
)


def _load() -> dict[str, dict[str, Any]]:
    if not STRATEGY_HALT_FILE.exists():
        return {}
    try:
        return json.loads(STRATEGY_HALT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning(
            "strategy_halt_state.json unreadable (%s); treating as empty",
            exc,
        )
        return {}


def _save(state: dict[str, dict[str, Any]]) -> None:
    STRATEGY_HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STRATEGY_HALT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STRATEGY_HALT_FILE)


def is_strategy_halted(strategy_id: str) -> bool:
    """True if the named strategy is currently halted at the strategy layer.

    Cross-cuts foundation.kill_switch.is_halted (which is per-market) —
    callers that want "should I dispatch this strategy at all" must check
    BOTH the market halt and the strategy halt.
    """
    return bool(_load().get(strategy_id, {}).get("halted", False))


def halt_strategy(
    strategy_id: str,
    reason: str,
    consecutive_exceptions: int = 0,
) -> None:
    """Mark a strategy as halted.

    Idempotent — repeated halts replace the previous halt's metadata but
    do not append. Does NOT raise; the caller (usually the isolation
    helper) needs the cycle to continue regardless.
    """
    state = _load()
    state[strategy_id] = {
        "halted": True,
        "reason": reason,
        "halted_at": datetime.now(timezone.utc).isoformat(),
        "consecutive_exceptions": int(consecutive_exceptions),
    }
    _save(state)
    _log.error(
        "STRATEGY HALTED [%s] reason=%s consec_exc=%d",
        strategy_id, reason, consecutive_exceptions,
    )


def reset_strategy(strategy_id: str, authorized_by: str, reason: str) -> None:
    """Clear a strategy's halt flag. Requires an authorization string for the audit trail."""
    state = _load()
    state[strategy_id] = {
        "halted": False,
        "reset_at": datetime.now(timezone.utc).isoformat(),
        "reset_by": authorized_by,
        "reset_reason": reason,
    }
    _save(state)
    _log.info("STRATEGY RESET [%s] by=%s reason=%s",
              strategy_id, authorized_by, reason)


def list_halted_strategies() -> list[str]:
    """Names of all strategies whose halted flag is currently True."""
    return [sid for sid, entry in _load().items() if entry.get("halted")]
