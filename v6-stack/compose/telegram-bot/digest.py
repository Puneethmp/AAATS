"""
AAATS v6 — Telegram daily digest builder + scheduler.

Sent once per UTC day at DIGEST_UTC_HOUR (default 18:00 UTC ≈ 23:30 IST) to
TELEGRAM_CHAT_SYSTEM with disable_notification=True (P2/silent).
Idempotent: aaats:bot:last_digest_date prevents double-send across bot restarts.

Real PnL/positions/strategy data lands in Phase κ; this module renders
placeholders for those rows today and pulls live values from Redis for the
rows that exist (cycle, restarts, queue depth, halt status, uptime).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from html import escape
from typing import Optional

import redis.asyncio as aioredis
from aiogram import Bot
from aiogram.enums import ParseMode

LOG = logging.getLogger("digest")

DIGEST_UTC_HOUR = int(os.environ.get("DIGEST_UTC_HOUR", "18"))
LAST_DIGEST_KEY = "aaats:bot:last_digest_date"
ALERT_LIST      = os.environ.get("ALERT_LIST", "aaats:alerts:queue")


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m:02d}m"


async def build_digest(redis: aioredis.Redis, bot_started_at: datetime) -> str:
    now = datetime.now(timezone.utc)

    try:
        eng    = await redis.get("aaats:hb:engine")
        wd     = await redis.get("aaats:hb:watchdog")
        rc     = await redis.get("aaats:metrics:auto_restarts") or b"0"
        ql     = await redis.llen(ALERT_LIST)
        halt   = await redis.get("aaats:halt:requested")
    except Exception as e:  # noqa: BLE001
        LOG.error("digest gather failed: %s", e)
        return f"🛠 <b>Daily digest</b>\n\nfailed to gather state: {escape(str(e))}"

    engine_cycle = "?"
    if eng:
        try:
            engine_cycle = eng.decode().split(":", 2)[1]
        except Exception:  # noqa: BLE001
            pass

    halt_str = halt.decode() if halt else "(none)"
    bot_uptime = _format_age((now - bot_started_at).total_seconds())

    rows = {
        "date":            now.strftime("%Y-%m-%d"),
        "bot uptime":      bot_uptime,
        "engine cycle":    engine_cycle,
        "auto restarts":   int(rc),
        "queue depth":     ql,
        "halt request":    halt_str,
        "PnL realised":    "—  (Phase κ)",
        "PnL unrealised":  "—  (Phase κ)",
        "open positions":  "—  (Phase κ)",
        "strategy state":  "—  (Phase κ)",
    }

    pad = 16
    lines = ["🛠 <b>AAATS v6 daily digest</b>", ""]
    lines.extend(
        f"<code>{escape(key.ljust(pad))} {escape(str(val))}</code>"
        for key, val in rows.items()
    )
    return "\n".join(lines)


async def digest_scheduler(
    bot: Bot,
    redis: aioredis.Redis,
    system_chat_id: int,
    bot_started_at: datetime,
) -> None:
    """Wake every 30s; emit digest exactly once per UTC day at DIGEST_UTC_HOUR."""
    if not system_chat_id:
        LOG.warning("system chat id not configured; digest scheduler will not send")
        return
    LOG.info(
        "digest scheduler started; UTC hour=%d, system chat=%s",
        DIGEST_UTC_HOUR, system_chat_id,
    )
    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.hour == DIGEST_UTC_HOUR:
                today_iso = now.date().isoformat()
                last = await redis.get(LAST_DIGEST_KEY)
                if (last.decode() if last else None) != today_iso:
                    text = await build_digest(redis, bot_started_at)
                    try:
                        await bot.send_message(
                            chat_id=system_chat_id, text=text,
                            parse_mode=ParseMode.HTML,
                            disable_notification=True,
                        )
                        await redis.set(LAST_DIGEST_KEY, today_iso, ex=60 * 60 * 48)
                        LOG.info("digest sent for %s", today_iso)
                    except Exception as e:  # noqa: BLE001
                        LOG.error("digest send failed: %s", e)
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            LOG.info("digest scheduler cancelled")
            return
        except Exception as e:  # noqa: BLE001
            LOG.error("digest scheduler error: %s", e)
            await asyncio.sleep(30)
