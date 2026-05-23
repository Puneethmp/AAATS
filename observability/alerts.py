"""
Telegram alert sender for AAATS.
Used by foundation modules (health monitor, kill switch) from Phase 0 onward.
Full observability stack (dashboard, diagnostics) is built in Phase 8.

Every message is prefixed with a market tag: [US], [INDIA], [CRYPTO], [SYSTEM].
Alert failures are silently swallowed — they must never crash the trading engine.

Usage:
    from observability.alerts import send_alert
    send_alert("Position halted — drawdown limit hit", market="us")

Each send is ALSO appended to data/alerts_log.json (atomic .tmp+replace) so
the daily digest can report fired/open/resolved counts over the 24h window.
The log write is best-effort; failures do not block Telegram or the trading loop.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Severity inference ──────────────────────────────────────────────────────


_SEVERITY_TOKENS = (
    ("critical", "critical"),
    ("halt", "critical"),
    ("kill switch", "critical"),
    ("error", "warn"),
    ("warn", "warn"),
    ("warning", "warn"),
    ("⚠️", "warn"),
    ("🛑", "critical"),
)


def _infer_severity(message: str) -> str:
    """Best-effort severity classification from message body text. Default
    ``info``. Callers can override with the ``severity=`` kwarg on send_alert.
    """
    body = message.lower()
    for token, sev in _SEVERITY_TOKENS:
        if token in body:
            return sev
    return "info"


def _alerts_log_path() -> Path:
    return Path(os.environ.get("AAATS_DATA", "data")) / "alerts_log.json"


def _append_alerts_log(entry: dict[str, Any]) -> None:
    """Atomic append: read existing JSON list, append, write to .tmp, rename.

    Schema per row: {ts (UTC ISO), market, severity, message, correlation_id}.
    On read failure we treat the log as empty; on write failure we swallow
    (alert-log loss is preferable to blocking the trading loop). The .tmp
    write + os.replace pattern survives a SIGINT mid-write: either the old
    file is intact, or the new file fully replaces it.
    """
    try:
        path = _alerts_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]]
        if path.exists():
            try:
                existing_raw = json.loads(path.read_text(encoding="utf-8"))
                existing = existing_raw if isinstance(existing_raw, list) else []
            except (OSError, json.JSONDecodeError):
                existing = []
        else:
            existing = []
        existing.append(entry)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(existing), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: silent-except — alert-log loss is acceptable; never block the caller
        pass


def send_alert(
    message: str,
    market: str = "system",
    *,
    severity: str | None = None,
    correlation_id: str | None = None,
) -> str:
    """
    Send a Telegram message tagged with the market prefix and append a row
    to ``data/alerts_log.json``.

    If credentials are not configured, the Telegram send is a no-op but the
    log row is still written (so paper-mode and dry-run sessions still build
    a digest-feedable history). Any send failure is caught and silenced —
    alert loss is preferable to crashing the trading loop.

    Args:
        message:        Alert body text.
        market:         Market tag prepended to message as [MARKET].
        severity:       Optional override; auto-inferred from message body
                        otherwise. Valid: ``info | warn | critical``.
        correlation_id: Optional caller-supplied ID for cross-system tracing.
                        Auto-generated (UUID4) when omitted.

    Returns:
        The correlation_id used for this alert (caller can stash it for
        later resolution wiring).
    """
    cid = correlation_id or str(uuid.uuid4())
    sev = severity if severity in ("info", "warn", "critical") else _infer_severity(message)

    _append_alerts_log({
        "ts": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "severity": sev,
        "message": message,
        "correlation_id": cid,
    })

    token = os.environ.get("ALERTS__TELEGRAM_BOT_TOKEN") or os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )
    chat_id = os.environ.get("ALERTS__TELEGRAM_CHAT_ID") or os.environ.get(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:
        return cid

    tag = f"[{market.upper()}]"
    full_message = f"{tag} {message}"

    try:
        asyncio.run(_send_async(token, chat_id, full_message))
    except RuntimeError:
        # asyncio.run() raises RuntimeError if an event loop is already running
        # (e.g. inside an async context). Schedule as a task instead.
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(_send_async(token, chat_id, full_message))
        except Exception:  # noqa: silent-except — alert send failure must never crash the trading loop
            pass
    except Exception:  # noqa: silent-except — alert send failure must never crash the trading loop
        pass
    return cid


async def _send_async(token: str, chat_id: str, message: str) -> None:
    """Async inner sender — isolated so failures don't propagate."""
    try:
        from telegram import Bot

        bot = Bot(token=token)
        async with bot:
            await bot.send_message(chat_id=chat_id, text=message)
    except Exception:  # noqa: silent-except — alert send failure must never crash the trading loop
        pass
