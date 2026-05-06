"""
Telegram alert sender for AAATS.
Used by foundation modules (health monitor, kill switch) from Phase 0 onward.
Full observability stack (dashboard, diagnostics) is built in Phase 8.

Every message is prefixed with a market tag: [US], [INDIA], [CRYPTO], [SYSTEM].
Alert failures are silently swallowed — they must never crash the trading engine.

Usage:
    from observability.alerts import send_alert
    send_alert("Position halted — drawdown limit hit", market="us")
"""

import asyncio
import os
from typing import Optional


def send_alert(message: str, market: str = "system") -> None:
    """
    Send a Telegram message tagged with the market prefix.

    If credentials are not configured, the call is a no-op (logged, not raised).
    Any send failure is caught and silenced — alert loss is preferable to
    crashing the trading loop.

    Args:
        message: Alert body text.
        market:  Market tag prepended to message as [MARKET].
    """
    token = os.environ.get("ALERTS__TELEGRAM_BOT_TOKEN") or os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )
    chat_id = os.environ.get("ALERTS__TELEGRAM_CHAT_ID") or os.environ.get(
        "TELEGRAM_CHAT_ID"
    )

    if not token or not chat_id:
        return

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
        except Exception:
            pass
    except Exception:
        pass


async def _send_async(token: str, chat_id: str, message: str) -> None:
    """Async inner sender — isolated so failures don't propagate."""
    try:
        from telegram import Bot

        bot = Bot(token=token)
        async with bot:
            await bot.send_message(chat_id=chat_id, text=message)
    except Exception:
        pass
