"""
AAATS v6 — Telegram message formatters.

Concise, mobile-friendly, emoji-prefixed; no raw JSON dumps.
HTML parse mode (cleaner escapes than Markdown).
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any


LEVEL_EMOJI = {
    "P0":   "🚨",
    "P1":   "🚨",
    "P2":   "🛠",
    "INFO": "🛠",
    "WARN": "⚠️",
}

CHANNEL_EMOJI = {
    "CRITICAL": "🚨",
    "TRADES":   "📈",
    "SYSTEM":   "🛠",
}


def _short_ts(ts_iso: str) -> str:
    """Render an ISO timestamp as HH:MMZ (UTC)."""
    try:
        dt = datetime.fromisoformat(ts_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%H:%MZ")
    except (ValueError, TypeError):
        return "?"


def _kv_lines(fields: dict[str, Any], pad: int = 16) -> str:
    """Render a flat dict as left-aligned key/value lines (monospace)."""
    out: list[str] = []
    for key, value in fields.items():
        if isinstance(value, (dict, list, tuple)):
            value = repr(value)
        s = str(value)
        if len(s) > 60:
            s = s[:57] + "…"
        out.append(f"<code>{escape(key.ljust(pad))} {escape(s)}</code>")
    return "\n".join(out)


def format_alert(alert: dict[str, Any]) -> str:
    """Render an alert payload as a Telegram HTML message.

    Honoured fields: ts, source, level, channel, code, title, message, fields.
    Back-compat: legacy 'extra' is treated as 'fields' if no 'fields' key.
    """
    level   = (alert.get("level") or "INFO").upper()
    channel = (alert.get("channel") or "").upper()
    code    = alert.get("code") or "alert"
    title   = alert.get("title") or code.replace("_", " ").capitalize()
    message = alert.get("message") or ""
    fields  = alert.get("fields") or alert.get("extra") or {}
    when    = _short_ts(alert.get("ts", ""))
    source  = alert.get("source") or ""

    emoji = CHANNEL_EMOJI.get(channel) or LEVEL_EMOJI.get(level, "•")

    enriched: dict[str, Any] = dict(fields)  # shallow copy, preserve insertion order
    if when and "when" not in enriched:
        enriched["when"] = when
    if source and "source" not in enriched:
        enriched["source"] = source

    lines = [f"{emoji} <b>{escape(title)}</b>"]
    if message:
        m = message if len(message) < 200 else message[:197] + "…"
        lines.append(escape(m))
    if enriched:
        lines.append("")
        lines.append(_kv_lines(enriched))
    return "\n".join(lines)


def format_status(state: dict[str, Any]) -> str:
    """Render a system status snapshot."""
    lines = ["🟢 <b>AAATS v6 status</b>", ""]
    fields: dict[str, Any] = {
        "engine HB":     state.get("engine_hb_summary", "?"),
        "watchdog HB":   state.get("watchdog_hb_summary", "?"),
        "auto restarts": state.get("auto_restarts", "?"),
        "alerts queue":  state.get("queue_depth", "?"),
        "halt request":  state.get("halt_request") or "(none)",
        "uptime":        state.get("uptime", "?"),
    }
    lines.append(_kv_lines(fields, pad=14))
    return "\n".join(lines)


def format_ack(emoji: str, headline: str, detail: str | None = None) -> str:
    out = [f"{emoji} <b>{escape(headline)}</b>"]
    if detail:
        out.append(escape(detail))
    return "\n".join(out)


def format_refusal(reason: str) -> str:
    return f"⛔ <b>refused</b> — {escape(reason)}"
