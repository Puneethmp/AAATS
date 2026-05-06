"""
AAATS v6 — Telegram webhook bot (Phase ζ; aiogram v3 + FastAPI + uvicorn).

See TELEGRAM_BOT_ARCHITECTURE.md (workspace) for the operational model.

- Webhook mode only (no polling).
- Three Telegram channels by category: CRITICAL / TRADES / SYSTEM.
- P0/P1/P2 severity model; bot routes by alert.channel, falls back by level/code.
- Inline-keyboard confirmation for /restart and /kill (10s expiry).
- Daily digest at DIGEST_UTC_HOUR to SYSTEM chat (silent).
- Strict chat allowlist + admin user allowlist for sensitive commands.
- Real PnL/positions/budget/risk/logs land in Phase κ (placeholders today).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
import uvicorn
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, Message, Update,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from digest import digest_scheduler
from formatters import format_ack, format_alert, format_refusal, format_status

LOG = logging.getLogger("telegram_bot")

# ============================================================================
# Configuration
# ============================================================================

BOT_TOKEN_FILE          = os.environ.get("BOT_TOKEN_FILE",          "/run/secrets/telegram_bot_token")
WEBHOOK_SECRET_FILE     = os.environ.get("WEBHOOK_SECRET_FILE",     "/run/secrets/telegram_webhook_secret")
GRAFANA_TOKEN_FILE      = os.environ.get("GRAFANA_WEBHOOK_TOKEN_FILE", "/run/secrets/grafana_webhook_token")
PUBLIC_URL          = os.environ.get("TELEGRAM_PUBLIC_URL", "")
WEBHOOK_PATH        = os.environ.get("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook")
LISTEN_PORT         = int(os.environ.get("TELEGRAM_LISTEN_PORT", "8080"))


def _csv_ints(env_name: str) -> frozenset[int]:
    raw = os.environ.get(env_name, "")
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return frozenset(out)


CHAT_ID_ALLOWLIST = _csv_ints("TELEGRAM_CHAT_ID_ALLOWLIST")
ADMIN_USER_IDS    = _csv_ints("TELEGRAM_ADMIN_USER_IDS")

_DEFAULT_CHAT = next(iter(CHAT_ID_ALLOWLIST), 0)
CHANNELS = {
    "CRITICAL": int(os.environ.get("TELEGRAM_CHAT_CRITICAL") or _DEFAULT_CHAT or 0),
    "TRADES":   int(os.environ.get("TELEGRAM_CHAT_TRADES")   or _DEFAULT_CHAT or 0),
    "SYSTEM":   int(os.environ.get("TELEGRAM_CHAT_SYSTEM")   or _DEFAULT_CHAT or 0),
}

REDIS_HOST          = os.environ.get("REDIS_HOST", "aaats-redis")
REDIS_PORT          = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD_FILE = os.environ.get("REDIS_PASSWORD_FILE", "/run/secrets/redis_password")

ALERT_LIST          = os.environ.get("ALERT_LIST", "aaats:alerts:queue")
HALT_REQUEST_KEY    = os.environ.get("HALT_REQUEST_KEY", "aaats:halt:requested")
RESTART_REQUEST_KEY = os.environ.get("RESTART_REQUEST_KEY", "aaats:restart:requested")
KILL_PENDING_TTL_S  = int(os.environ.get("KILL_PENDING_TTL_S", "10"))

START_TIME = datetime.now(timezone.utc)


# ============================================================================
# Process-level shared state
# ============================================================================

class _State:
    bot: Optional[Bot] = None
    dp: Optional[Dispatcher] = None
    redis: Optional[aioredis.Redis] = None
    consumer_task: Optional[asyncio.Task] = None
    digest_task: Optional[asyncio.Task] = None

state = _State()


# ============================================================================
# Auth + helpers
# ============================================================================

def _is_allowed_chat(chat_id: int) -> bool:
    return chat_id in CHAT_ID_ALLOWLIST


def _is_admin_user(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS


def _read_secret(path: str) -> str:
    try:
        return open(path, "r", encoding="utf-8").read().strip()
    except OSError as e:
        LOG.warning("cannot read %s: %s", path, e)
        return ""


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s:02d}s"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h {m:02d}m"


# ============================================================================
# Channel routing
# ============================================================================

_TRADE_CODE_HINTS = ("trade", "order", "position", "fill", "pnl", "execution_")


def channel_for_alert(alert: dict) -> int:
    explicit = (alert.get("channel") or "").upper()
    if explicit in CHANNELS and CHANNELS[explicit]:
        return CHANNELS[explicit]
    code  = (alert.get("code")  or "").lower()
    level = (alert.get("level") or "").upper()
    if any(hint in code for hint in _TRADE_CODE_HINTS):
        return CHANNELS["TRADES"] or CHANNELS["CRITICAL"] or CHANNELS["SYSTEM"]
    if level in ("P0", "P1"):
        return CHANNELS["CRITICAL"] or CHANNELS["SYSTEM"]
    return CHANNELS["SYSTEM"] or CHANNELS["CRITICAL"]


def is_silent_level(alert: dict) -> bool:
    level = (alert.get("level") or "").upper()
    return level in ("P2", "INFO")


# ============================================================================
# Background workers
# ============================================================================

async def alert_consumer(bot: Bot, redis: aioredis.Redis) -> None:
    LOG.info("alert consumer started; channels=%s", CHANNELS)
    while True:
        try:
            result = await redis.brpop([ALERT_LIST], timeout=5)
            if result is None:
                continue
            _key, raw = result
            try:
                alert = json.loads(raw)
            except json.JSONDecodeError:
                LOG.warning("malformed alert: %r", raw[:200])
                continue
            chat = channel_for_alert(alert)
            if not chat:
                LOG.warning("no chat for channel; dropping alert code=%s", alert.get("code"))
                continue
            text = format_alert(alert)
            silent = is_silent_level(alert)
            try:
                await bot.send_message(
                    chat_id=chat, text=text, parse_mode=ParseMode.HTML,
                    disable_notification=silent,
                )
            except TelegramAPIError as e:
                LOG.warning("send failed (chat=%s): %s", chat, e)
        except asyncio.CancelledError:
            LOG.info("alert consumer cancelled")
            return
        except Exception as e:  # noqa: BLE001
            LOG.error("alert consumer error: %s", e)
            await asyncio.sleep(2)


# ============================================================================
# Status snapshot
# ============================================================================

async def gather_status(redis: aioredis.Redis) -> dict:
    now = datetime.now(timezone.utc)
    out: dict = {}
    try:
        eng  = await redis.get("aaats:hb:engine")
        wd   = await redis.get("aaats:hb:watchdog")
        rc   = await redis.get("aaats:metrics:auto_restarts") or b"0"
        ql   = await redis.llen(ALERT_LIST)
        halt = await redis.get(HALT_REQUEST_KEY)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    if eng:
        try:
            ts, cycle, status = eng.decode().split(":", 2)
            age = now.timestamp() - float(ts)
            out["engine_hb_summary"] = f"cycle {cycle}, age {_format_age(age)}, {status}"
        except Exception:  # noqa: BLE001
            out["engine_hb_summary"] = eng.decode()
    else:
        out["engine_hb_summary"] = "MISSING"

    if wd:
        try:
            ts, status = wd.decode().split(":", 1)
            age = now.timestamp() - float(ts)
            out["watchdog_hb_summary"] = f"age {_format_age(age)}, {status}"
        except Exception:  # noqa: BLE001
            out["watchdog_hb_summary"] = wd.decode()
    else:
        out["watchdog_hb_summary"] = "MISSING"

    out["auto_restarts"] = int(rc)
    out["queue_depth"]   = ql
    out["halt_request"]  = halt.decode() if halt else None
    out["uptime"]        = _format_age((now - START_TIME).total_seconds())
    return out


def status_keyboard(_is_admin: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Restart", callback_data="status:restart")
    kb.button(text="⏸ Pause",   callback_data="status:pause")
    kb.button(text="▶️ Resume",  callback_data="status:resume")
    kb.button(text="📊 Metrics", callback_data="status:metrics")
    kb.button(text="📜 Logs",    callback_data="status:logs")
    kb.button(text="💀 Kill",    callback_data="status:kill")
    kb.adjust(3, 3)
    return kb.as_markup()


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Confirm", callback_data=f"{action}:confirm")
    kb.button(text="❌ Cancel",  callback_data=f"{action}:cancel")
    kb.adjust(2)
    return kb.as_markup()


async def _expire_after(message: Message, seconds: int, fallback_text: str) -> None:
    await asyncio.sleep(seconds)
    try:
        await message.edit_text(fallback_text, parse_mode=ParseMode.HTML)
    except TelegramAPIError:
        # Already edited (Confirm/Cancel pressed) — ignore.
        pass


# ============================================================================
# Routers
# ============================================================================

router = Router()


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    await message.answer(
        "<b>AAATS v6 ops bot — Phase ζ</b>\n\n"
        "<code>/status</code>     service health + actions\n"
        "<code>/positions</code>  open positions\n"
        "<code>/pnl</code>        realised + unrealised P&amp;L\n"
        "<code>/budget</code>     LLM token bucket\n"
        "<code>/risk</code>       risk caps + utilisation\n"
        "<code>/cycle</code>      engine HB cycle id\n"
        "<code>/logs</code>       last 20 lines from engine\n"
        "<code>/pause</code>      ⚠️ engine pause (admin)\n"
        "<code>/resume</code>     ▶️ clear pause (admin)\n"
        "<code>/restart</code>    🔁 restart engine (admin, confirm)\n"
        "<code>/kill</code>       💀 halt engine (admin, confirm)\n",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    snap = await gather_status(state.redis)
    if "error" in snap:
        await message.answer(format_refusal(f"redis: {snap['error']}"))
        return
    await message.answer(
        format_status(snap),
        reply_markup=status_keyboard(_is_admin_user(message.from_user.id)),
    )


@router.message(Command("cycle"))
async def cmd_cycle(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    eng = await state.redis.get("aaats:hb:engine")
    if not eng:
        await message.answer("⚠️ no heartbeat — engine may be down")
        return
    try:
        cycle = eng.decode().split(":", 2)[1]
    except Exception:  # noqa: BLE001
        cycle = "?"
    await message.answer(f"engine cycle: <code>{cycle}</code>")


# ---- Placeholder commands (Phase κ wires real data) -----------------------

@router.message(Command("positions"))
async def cmd_positions(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    await message.answer(format_ack("📈", "Open positions",
                                     "(Phase κ wires real data — engine port required)"))


@router.message(Command("pnl"))
async def cmd_pnl(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    await message.answer(format_ack("📈", "P&L", "(Phase κ wires real data)"))


@router.message(Command("budget"))
async def cmd_budget(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    await message.answer(format_ack("🛠", "Token budget", "(Phase κ wires real data)"))


@router.message(Command("risk"))
async def cmd_risk(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    await message.answer(format_ack("🛠", "Risk caps + utilisation", "(Phase κ wires real data)"))


@router.message(Command("logs"))
async def cmd_logs(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    await message.answer(format_ack("📜", "Engine logs",
                                     "(Phase κ wires real data — last 20 engine lines)"))


# ---- Admin-only state mutators --------------------------------------------

@router.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    if not _is_admin_user(message.from_user.id):
        await message.answer(format_refusal("admin only"))
        return
    await state.redis.set(HALT_REQUEST_KEY, "pause", ex=86400)
    await message.answer(format_ack("⏸", "Pause requested",
                                     "engine reads aaats:halt:requested on next cycle"))


@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    if not _is_admin_user(message.from_user.id):
        await message.answer(format_refusal("admin only"))
        return
    n = await state.redis.delete(HALT_REQUEST_KEY)
    await message.answer(format_ack("▶️", "Pause cleared",
                                     f"removed {n} halt key{'s' if n != 1 else ''}"))


@router.message(Command("kill"))
async def cmd_kill(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    if not _is_admin_user(message.from_user.id):
        await message.answer(format_refusal("admin only"))
        return
    sent = await message.answer(
        f"⚠️ <b>KILL armed</b>\nConfirm within {KILL_PENDING_TTL_S}s to halt the engine.",
        reply_markup=confirm_keyboard("kill"),
    )
    asyncio.create_task(
        _expire_after(sent, KILL_PENDING_TTL_S, "❌ <b>KILL cancelled</b> (timeout)")
    )


@router.message(Command("restart"))
async def cmd_restart(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        return
    if not _is_admin_user(message.from_user.id):
        await message.answer(format_refusal("admin only"))
        return
    sent = await message.answer(
        f"⚠️ <b>RESTART armed</b>\nConfirm within {KILL_PENDING_TTL_S}s "
        "to recreate the engine container.",
        reply_markup=confirm_keyboard("restart"),
    )
    asyncio.create_task(
        _expire_after(sent, KILL_PENDING_TTL_S, "❌ <b>RESTART cancelled</b> (timeout)")
    )


# ---- Confirmation callbacks -----------------------------------------------

@router.callback_query(F.data == "kill:confirm")
async def cb_kill_confirm(query: CallbackQuery) -> None:
    if not _is_admin_user(query.from_user.id):
        await query.answer("admin only", show_alert=True)
        return
    payload = f"kill:{query.from_user.id}:{int(time.time())}"
    await state.redis.set(HALT_REQUEST_KEY, payload, ex=86400)
    await query.message.edit_text(
        "💀 <b>KILL CONFIRMED</b>\nhalt request written; engine reads on next cycle."
    )
    await query.answer("done")


@router.callback_query(F.data == "kill:cancel")
async def cb_kill_cancel(query: CallbackQuery) -> None:
    await query.message.edit_text("❌ <b>KILL cancelled</b>")
    await query.answer("cancelled")


@router.callback_query(F.data == "restart:confirm")
async def cb_restart_confirm(query: CallbackQuery) -> None:
    if not _is_admin_user(query.from_user.id):
        await query.answer("admin only", show_alert=True)
        return
    payload = f"restart:{query.from_user.id}:{int(time.time())}"
    await state.redis.set(RESTART_REQUEST_KEY, payload, ex=86400)
    await query.message.edit_text(
        "🔁 <b>RESTART requested</b>\n"
        "Phase κ wires this to the watchdog; for now recorded as intent in "
        "<code>aaats:restart:requested</code>."
    )
    await query.answer("recorded")


@router.callback_query(F.data == "restart:cancel")
async def cb_restart_cancel(query: CallbackQuery) -> None:
    await query.message.edit_text("❌ <b>RESTART cancelled</b>")
    await query.answer("cancelled")


# ---- Quick-action callbacks (from /status keyboard) -----------------------

@router.callback_query(F.data == "status:metrics")
async def cb_status_metrics(query: CallbackQuery) -> None:
    if not _is_allowed_chat(query.message.chat.id):
        await query.answer()
        return
    snap = await gather_status(state.redis)
    await query.message.answer(format_status(snap))
    await query.answer()


@router.callback_query(F.data == "status:logs")
async def cb_status_logs(query: CallbackQuery) -> None:
    await query.message.answer(format_ack("📜", "Engine logs", "(Phase κ wires real data)"))
    await query.answer()


@router.callback_query(F.data == "status:pause")
async def cb_status_pause(query: CallbackQuery) -> None:
    if not _is_admin_user(query.from_user.id):
        await query.answer("admin only", show_alert=True)
        return
    await state.redis.set(HALT_REQUEST_KEY, "pause", ex=86400)
    await query.message.answer(format_ack("⏸", "Pause requested", "via inline button"))
    await query.answer("paused")


@router.callback_query(F.data == "status:resume")
async def cb_status_resume(query: CallbackQuery) -> None:
    if not _is_admin_user(query.from_user.id):
        await query.answer("admin only", show_alert=True)
        return
    n = await state.redis.delete(HALT_REQUEST_KEY)
    await query.message.answer(format_ack("▶️", "Pause cleared", f"deleted {n} key"))
    await query.answer("resumed")


@router.callback_query(F.data == "status:kill")
async def cb_status_kill(query: CallbackQuery) -> None:
    if not _is_admin_user(query.from_user.id):
        await query.answer("admin only", show_alert=True)
        return
    sent = await query.message.answer(
        f"⚠️ <b>KILL armed</b>\nConfirm within {KILL_PENDING_TTL_S}s.",
        reply_markup=confirm_keyboard("kill"),
    )
    asyncio.create_task(
        _expire_after(sent, KILL_PENDING_TTL_S, "❌ <b>KILL cancelled</b> (timeout)")
    )
    await query.answer()


@router.callback_query(F.data == "status:restart")
async def cb_status_restart(query: CallbackQuery) -> None:
    if not _is_admin_user(query.from_user.id):
        await query.answer("admin only", show_alert=True)
        return
    sent = await query.message.answer(
        f"⚠️ <b>RESTART armed</b>\nConfirm within {KILL_PENDING_TTL_S}s.",
        reply_markup=confirm_keyboard("restart"),
    )
    asyncio.create_task(
        _expire_after(sent, KILL_PENDING_TTL_S, "❌ <b>RESTART cancelled</b> (timeout)")
    )
    await query.answer()


# ---- Catch-all (must be registered last) ----------------------------------

@router.message()
async def silent_drop(message: Message) -> None:
    if not _is_allowed_chat(message.chat.id):
        LOG.warning(
            "REJECT chat=%s user=@%s",
            message.chat.id,
            message.from_user.username if message.from_user else "?",
        )
        return
    await message.answer("unknown command — try /help")


# ============================================================================
# FastAPI app + lifespan
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    token = _read_secret(BOT_TOKEN_FILE)
    if not token:
        raise RuntimeError(f"bot token unreadable from {BOT_TOKEN_FILE}")
    if not CHAT_ID_ALLOWLIST:
        raise RuntimeError("TELEGRAM_CHAT_ID_ALLOWLIST is empty — refusing to start")
    if not ADMIN_USER_IDS:
        LOG.warning("TELEGRAM_ADMIN_USER_IDS is empty — sensitive commands have no admins")
    if not PUBLIC_URL:
        raise RuntimeError("TELEGRAM_PUBLIC_URL is empty — cloudflared-bot must publish a URL first")

    LOG.info(
        "telegram-bot starting. listen=:%d webhook=%s%s allowlist=%s admins=%s channels=%s digest_hour=UTC%s",
        LISTEN_PORT, PUBLIC_URL, WEBHOOK_PATH,
        sorted(CHAT_ID_ALLOWLIST), sorted(ADMIN_USER_IDS), CHANNELS,
        os.environ.get("DIGEST_UTC_HOUR", "18"),
    )

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    redis_pwd = _read_secret(REDIS_PASSWORD_FILE)
    redis = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=redis_pwd,
        socket_timeout=30, socket_keepalive=True,
    )
    await redis.ping()

    state.bot = bot
    state.dp = dp
    state.redis = redis

    webhook_url = f"{PUBLIC_URL.rstrip('/')}{WEBHOOK_PATH}"
    webhook_secret = _read_secret(WEBHOOK_SECRET_FILE) or None
    await bot.set_webhook(
        url=webhook_url,
        secret_token=webhook_secret,
        drop_pending_updates=True,
        allowed_updates=dp.resolve_used_update_types(),
    )

    state.consumer_task = asyncio.create_task(
        alert_consumer(bot, redis), name="alert_consumer",
    )
    state.digest_task = asyncio.create_task(
        digest_scheduler(bot, redis, CHANNELS["SYSTEM"], START_TIME),
        name="digest_scheduler",
    )

    LOG.info("startup complete; webhook registered")

    try:
        yield
    finally:
        LOG.info("shutting down")
        for task in (state.consumer_task, state.digest_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        try:
            await bot.delete_webhook()
        except Exception as e:  # noqa: BLE001
            LOG.warning("delete_webhook failed: %s", e)
        await bot.session.close()
        try:
            await redis.aclose()
        except Exception:  # noqa: BLE001
            pass


app = FastAPI(
    lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None,
)


@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    return "ok"


@app.get("/ready", response_class=PlainTextResponse)
async def ready() -> str:
    if state.redis is None:
        raise HTTPException(503, "redis client not initialised")
    try:
        await state.redis.ping()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"redis unreachable: {e}")
    return "ready"


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus-format metrics derived from Redis state. Scraped by Alloy."""
    if state.redis is None:
        raise HTTPException(503, "redis not initialised")
    try:
        ql   = await state.redis.llen(ALERT_LIST)
        rc   = await state.redis.get("aaats:metrics:auto_restarts") or b"0"
        halt = await state.redis.get(HALT_REQUEST_KEY)
        eng  = await state.redis.get("aaats:hb:engine")
        wd   = await state.redis.get("aaats:hb:watchdog")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"redis error: {e}")

    now = datetime.now(timezone.utc).timestamp()

    def _hb_age(val: Optional[bytes]) -> float:
        if not val:
            return -1.0
        try:
            return now - float(val.decode().split(":", 1)[0])
        except (ValueError, UnicodeDecodeError):
            return -1.0

    eng_age_s = _hb_age(eng)
    wd_age_s  = _hb_age(wd)
    halt_active = 1 if halt else 0
    bot_uptime_s = (datetime.now(timezone.utc) - START_TIME).total_seconds()

    lines = [
        "# HELP aaats_alert_queue_depth Pending alerts in aaats:alerts:queue",
        "# TYPE aaats_alert_queue_depth gauge",
        f"aaats_alert_queue_depth {ql}",
        "# HELP aaats_engine_auto_restarts_total Engine container auto-restart count",
        "# TYPE aaats_engine_auto_restarts_total counter",
        f"aaats_engine_auto_restarts_total {int(rc)}",
        "# HELP aaats_engine_hb_age_seconds Age of last engine heartbeat (-1 if missing)",
        "# TYPE aaats_engine_hb_age_seconds gauge",
        f"aaats_engine_hb_age_seconds {eng_age_s:.3f}",
        "# HELP aaats_watchdog_hb_age_seconds Age of last watchdog heartbeat (-1 if missing)",
        "# TYPE aaats_watchdog_hb_age_seconds gauge",
        f"aaats_watchdog_hb_age_seconds {wd_age_s:.3f}",
        "# HELP aaats_halt_active 1 if a halt is currently requested",
        "# TYPE aaats_halt_active gauge",
        f"aaats_halt_active {halt_active}",
        "# HELP aaats_bot_uptime_seconds Bot process uptime",
        "# TYPE aaats_bot_uptime_seconds gauge",
        f"aaats_bot_uptime_seconds {bot_uptime_s:.0f}",
    ]
    return "\n".join(lines) + "\n"


# Mapping Grafana severity labels → AAATS levels
_GRAFANA_SEVERITY_LEVEL = {
    "critical": "P0", "high": "P0", "page": "P0",
    "warning":  "P1", "medium": "P1", "ticket": "P1",
    "info":     "P2", "low":    "P2", "none":   "P2",
}


@app.post("/grafana/alert")
async def grafana_alert(request: Request) -> dict:
    """Webhook receiver for Grafana Cloud alert rules.

    Translates the Grafana payload into the AAATS alert schema and pushes onto
    aaats:alerts:queue; the existing alert_consumer routes + formats + sends.
    Authenticates via Authorization: Bearer <token>.
    """
    expected = _read_secret(GRAFANA_TOKEN_FILE)
    if not expected:
        raise HTTPException(503, "grafana webhook auth not configured")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or auth[len("Bearer "):] != expected:
        LOG.warning("grafana webhook: rejected (missing/invalid bearer)")
        raise HTTPException(401, "invalid token")

    payload = await request.json()
    status = (payload.get("status") or "firing").lower()
    alerts = payload.get("alerts") or []
    pushed = 0

    for a in alerts:
        labels      = a.get("labels") or {}
        annotations = a.get("annotations") or {}
        severity    = (labels.get("severity") or "warning").lower()
        level       = _GRAFANA_SEVERITY_LEVEL.get(severity, "P1")
        if status == "resolved":
            level = "P2"

        explicit_channel = (labels.get("channel") or "").upper() or None
        alertname = labels.get("alertname") or "grafana_alert"

        title = alertname.replace("_", " ")
        if status == "resolved":
            title = f"{title} (resolved)"
        message = annotations.get("summary") or annotations.get("description") or ""

        # fields = labels minus housekeeping; clamp to 8 entries to keep mobile-friendly
        skip = {"alertname", "severity", "channel"}
        fields: dict = {}
        for k, v in labels.items():
            if k in skip:
                continue
            fields[k] = v
            if len(fields) >= 8:
                break

        out = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": "grafana",
            "level": level,
            "code": f"grafana_{alertname.lower()}_{status}",
            "title": f"📊 {title}" if status == "firing" else f"✅ {title}",
            "message": (message or "")[:240],
            "fields": fields,
        }
        if explicit_channel:
            out["channel"] = explicit_channel

        try:
            await state.redis.lpush(ALERT_LIST, json.dumps(out))
            await state.redis.ltrim(ALERT_LIST, 0, 999)
            pushed += 1
        except Exception as e:  # noqa: BLE001
            LOG.error("grafana → queue push failed: %s", e)

    return {"ok": True, "received": len(alerts), "pushed": pushed}


@app.post(WEBHOOK_PATH)
async def webhook(request: Request) -> dict:
    expected_secret = _read_secret(WEBHOOK_SECRET_FILE)
    got = request.headers.get("x-telegram-bot-api-secret-token", "")
    if expected_secret and got != expected_secret:
        LOG.warning("rejected webhook: secret mismatch")
        raise HTTPException(401, "invalid secret token")
    payload = await request.json()
    update = Update.model_validate(payload, context={"bot": state.bot})
    await state.dp.feed_update(state.bot, update)
    return {"ok": True}


# ============================================================================
# Entry point
# ============================================================================

def main() -> int:
    logging.basicConfig(
        level=os.environ.get("BOT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    uvicorn.run(
        "bot:app",
        host="0.0.0.0",
        port=LISTEN_PORT,
        log_level=os.environ.get("BOT_LOG_LEVEL", "info").lower(),
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
