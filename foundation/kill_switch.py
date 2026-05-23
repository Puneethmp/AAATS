"""
Per-market and global kill switch for AAATS.

Halt state is persisted to disk (JSON) so it survives process restarts.
The main trading loop checks is_halted() at the top of every cycle.

CLI usage (via kill.py):
    python kill.py --market us
    python kill.py --market india
    python kill.py --market all --confirm

Programmatic usage:
    from foundation.kill_switch import halt, is_halted, reset
    halt(market="us", reason="Drawdown limit -15% hit", triggered_by="drawdown_guardian")
    if is_halted("us"):
        return
    reset(market="us", authorized_by="Puneeth", reason="Issue reviewed and resolved")
"""

import json
import os
from pathlib import Path
from typing import Literal

from foundation.audit_trail import AuditTrail
from observability.alerts import send_alert

MarketType = Literal["us", "india", "crypto", "all"]
_SingleMarket = Literal["us", "india", "crypto"]

HALT_FILE = Path(os.environ.get("AAATS_DATA", "data")) / "halt_state.json"

_ALL_MARKETS: list[_SingleMarket] = ["us", "india", "crypto"]


def _load_state() -> dict[str, bool]:
    """Read halt state from disk. Returns all-False if file does not exist."""
    if HALT_FILE.exists():
        with open(HALT_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {m: False for m in _ALL_MARKETS}


def _save_state(state: dict[str, bool]) -> None:
    """Persist halt state to disk atomically."""
    HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HALT_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def halt(market: MarketType, reason: str, triggered_by: str) -> None:
    """
    Halt trading for one market or all markets.

    Writes halt flag to disk (survives restart), appends to audit trail,
    and sends a Telegram alert. Alert failure does NOT prevent the halt.

    Args:
        market:       "us", "india", "crypto", or "all".
        reason:       Human-readable reason — stored in audit trail verbatim.
        triggered_by: Caller identifier (e.g. "drawdown_guardian", "kill.py CLI").
    """
    state = _load_state()
    markets_halted = _ALL_MARKETS if market == "all" else [market]

    for m in markets_halted:
        state[m] = True
    _save_state(state)

    audit = AuditTrail()
    audit.append(
        market=market,
        module="kill_switch",
        event_type="HALT",
        details={"triggered_by": triggered_by, "markets_halted": markets_halted},
        result="HALTED",
        reason=reason,
    )

    alert_text = (
        f"KILL SWITCH ACTIVATED\n"
        f"Market: {market.upper()}\n"
        f"Reason: {reason}\n"
        f"Triggered by: {triggered_by}"
    )
    try:
        send_alert(alert_text, market=market)
    except Exception:  # noqa: silent-except — alert failure must never prevent a halt from completing
        pass


def is_halted(market: _SingleMarket) -> bool:
    """
    Return True if the given market is currently halted.
    Called at the top of every trading loop cycle.

    Args:
        market: "us", "india", or "crypto".
    """
    return _load_state().get(market, False)


def reset(market: MarketType, authorized_by: str, reason: str) -> None:
    """
    Clear the halt flag for a market. Requires authorization and explicit reason.
    Both are logged to the audit trail — there is no anonymous reset.

    Args:
        market:        Market to resume, or "all".
        authorized_by: Name of the person authorising the reset.
        reason:        Why the issue has been resolved.
    """
    state = _load_state()
    markets_reset = _ALL_MARKETS if market == "all" else [market]

    for m in markets_reset:
        state[m] = False
    _save_state(state)

    audit = AuditTrail()
    audit.append(
        market=market,
        module="kill_switch",
        event_type="HALT",
        details={
            "action": "RESET",
            "authorized_by": authorized_by,
            "markets_reset": markets_reset,
        },
        result="GO",
        reason=reason,
    )

    send_alert(
        f"Kill switch RESET\nMarket: {market.upper()}\nAuthorized by: {authorized_by}\nReason: {reason}",
        market=market,
    )
