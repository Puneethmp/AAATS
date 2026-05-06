"""
Redis-backed alert sender for AAATS v6 engine.

Replaces observability.alerts.send_alert: instead of calling python-telegram-bot
directly, LPUSH a JSON payload onto the Redis list aaats:alerts:queue. The
deployed telegram-bot container BRPOPs from this list and dispatches to
chat 1946109268 routed by the `channel` field.

This shim is wired in by engine/v6_engine.py at startup, before any code that
imports observability.alerts runs.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import redis

LOG = logging.getLogger("engine.redis_alerts")

REDIS_HOST = os.environ.get("REDIS_HOST", "aaats-redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD_FILE = os.environ.get("REDIS_PASSWORD_FILE", "/run/secrets/redis_password")
ALERT_LIST = os.environ.get("ALERT_LIST", "aaats:alerts:queue")

_TRADE_KEYWORDS = ("buy ", "sell ", "📈", "🟢", "🔴", "✅ buy", "✅ sell")
_HALT_KEYWORDS  = ("halt", "🛑", "⛔", "kill", "drawdown")

_client: Optional[redis.Redis] = None


def _read_password() -> str:
    try:
        with open(REDIS_PASSWORD_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return os.environ.get("REDIS_PASSWORD", "")


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=_read_password() or None,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _client


def _classify(message: str, market: str) -> tuple[str, str, str]:
    """Return (channel, level, code) inferred from message text + market tag."""
    m = message.lower()
    if any(k in m for k in _HALT_KEYWORDS):
        return "CRITICAL", "P1", "TRADE_HALT"
    if any(k in m for k in _TRADE_KEYWORDS):
        side = "BUY" if "buy" in m else "SELL"
        return "TRADES", "P2", f"TRADE_{side}"
    return "SYSTEM", "INFO", "ENGINE_EVENT"


def send_alert(message: str, market: str = "system") -> None:
    """
    Drop-in replacement for observability.alerts.send_alert.

    Same signature; never raises. Failures are logged at WARNING and silently
    dropped — the trading loop must not crash because alerts can't be sent.
    """
    try:
        channel, level, code = _classify(message, market)
        payload = {
            "ts":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source":  f"engine/{market}",
            "level":   level,
            "channel": channel,
            "code":    code,
            "title":   f"{market.upper()} {code.replace('_',' ').title()}",
            "message": message[:600],
            "fields":  {"market": market},
        }
        _get_client().lpush(ALERT_LIST, json.dumps(payload))
    except Exception as e:  # noqa: BLE001
        LOG.warning("alert push failed (dropped): %s", e)
