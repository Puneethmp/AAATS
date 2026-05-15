"""
AAATS Telegram Command Bot — python-telegram-bot v20+ polling mode.

Commands:
  /status    — capital, last cycle, regime, open positions count
  /positions — all open positions with entry price and age
  /pnl       — realized PnL summary by strategy
  /trades N  — last N trades (default 5)
  /stop      — activate kill switch (requires CONFIRM STOP reply)
  /help      — list commands

Reads data from:
  - /app/data/paper_trades.db   (trades + positions)
  - /app/data/state/            (heartbeat, cycle state)

Runs as a standalone Docker service alongside aaats-paper-crypto.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("aaats.telegram_bot")

# ── Config ────────────────────────────────────────────────────────────────────
TOKEN   = os.environ.get("ALERTS__TELEGRAM_BOT_TOKEN", "")
CHAT_ID = int(os.environ.get("ALERTS__TELEGRAM_CHAT_ID", "0"))
DB_PATH = Path(os.environ.get("DB_PATH", "/app/data/paper_trades.db"))
STATE_DIR = Path("/app/data/state")

# TOTP secret for /killall 2FA (set this via .env — same format as Angel TOTP).
# Generate one with: python -c "import pyotp; print(pyotp.random_base32())"
# Then add the seed to your authenticator app (Google Authenticator / Authy).
KILLALL_TOTP_SECRET = os.environ.get("KILLALL_TOTP_SECRET", "")

# ── DB helpers ────────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)
    )
    return cur.fetchone() is not None


# ── Command helpers ───────────────────────────────────────────────────────────

def _get_status() -> str:
    lines = ["📊 *AAATS Status*"]

    # Heartbeat / last cycle
    hb_file = STATE_DIR / "crypto_heartbeat.json"
    if hb_file.exists():
        try:
            hb = json.loads(hb_file.read_text())
            ts  = hb.get("timestamp", "?")[:19].replace("T", " ")
            cyc = hb.get("cycle_count", "?")
            lines.append(f"🕐 Last cycle: {ts} UTC (cycle #{cyc})")
        except Exception:
            lines.append("🕐 Heartbeat: unreadable")
    else:
        lines.append("🕐 Heartbeat: no data yet")

    # DB stats
    if DB_PATH.exists():
        try:
            conn = _db()
            if _table_exists(conn, "paper_trades"):
                row = conn.execute(
                    "SELECT COUNT(*) as n, SUM(CASE WHEN action='BUY' AND exit_time IS NULL THEN 1 ELSE 0 END) as open "
                    "FROM paper_trades"
                ).fetchone()
                total, open_pos = row["n"], row["open"] or 0
                lines.append(f"📈 Trades recorded: {total} | Open positions: {open_pos}")

                # Capital proxy from last known portfolio
                cap_file = Path("/app/data/portfolio.json")
                if cap_file.exists():
                    try:
                        portfolio = json.loads(cap_file.read_text())
                        cap = portfolio.get("crypto", {}).get("capital", "?")
                        lines.append(f"💰 Capital: USD {cap:.2f}" if isinstance(cap, float) else f"💰 Capital: {cap}")
                    except Exception:
                        pass
            conn.close()
        except Exception as e:
            lines.append(f"⚠️ DB error: {e}")
    else:
        lines.append("⚠️ DB not found — no trades yet")

    # Regime from state
    regime_file = STATE_DIR / "crypto_state.json"
    if regime_file.exists():
        try:
            state = json.loads(regime_file.read_text())
            regime = state.get("regime", "unknown")
            symbol = state.get("symbol", "")
            lines.append(f"🧭 Last regime: {regime} ({symbol})")
        except Exception:
            pass

    lines.append(f"\n_Updated: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}_")
    return "\n".join(lines)


def _get_positions() -> str:
    if not DB_PATH.exists():
        return "⚠️ No database yet — no trades recorded."
    try:
        conn = _db()
        if not _table_exists(conn, "paper_trades"):
            conn.close()
            return "⚠️ No trades table yet."
        rows = conn.execute(
            "SELECT symbol, price, entry_time, strategy, size_usd, notes "
            "FROM paper_trades "
            "WHERE action='BUY' AND exit_time IS NULL "
            "ORDER BY entry_time DESC"
        ).fetchall()
        conn.close()
    except Exception as e:
        return f"⚠️ DB error: {e}"

    if not rows:
        return "📭 No open positions — all flat."

    now = datetime.now(timezone.utc)
    lines = [f"📂 *Open Positions ({len(rows)})*"]
    for r in rows:
        entry_ts = r["entry_time"] or "?"
        age = ""
        if entry_ts and entry_ts != "?":
            try:
                dt = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
                hrs = (now - dt).total_seconds() / 3600
                age = f" | {hrs:.1f}h ago"
            except Exception:
                pass
        conf = ""
        if r["notes"]:
            try:
                n = json.loads(r["notes"])
                conf = f" | conf={n.get('confidence', 0):.2f}"
            except Exception:
                pass
        lines.append(
            f"• {r['symbol']} @ {r['price']:.4f} | {r['strategy'] or 'unknown'}{conf}{age}"
        )
    return "\n".join(lines)


def _get_pnl() -> str:
    if not DB_PATH.exists():
        return "⚠️ No database yet."
    try:
        conn = _db()
        if not _table_exists(conn, "paper_trades"):
            conn.close()
            return "⚠️ No trades table yet."
        rows = conn.execute(
            "SELECT strategy, COUNT(*) as trades, "
            "SUM(CASE WHEN pnl_pct IS NOT NULL THEN 1 ELSE 0 END) as closed, "
            "AVG(pnl_pct) as avg_pnl, SUM(pnl_pct) as total_pnl "
            "FROM paper_trades WHERE action='SELL' "
            "GROUP BY strategy ORDER BY total_pnl DESC"
        ).fetchall()
        conn.close()
    except Exception as e:
        return f"⚠️ DB error: {e}"

    if not rows:
        return "📭 No closed trades yet — system is in hold mode."

    lines = ["💹 *PnL by Strategy*"]
    for r in rows:
        strat = r["strategy"] or "unknown"
        avg   = r["avg_pnl"] or 0
        total = r["total_pnl"] or 0
        emoji = "🟢" if total > 0 else "🔴" if total < 0 else "⚪"
        lines.append(
            f"{emoji} {strat}: {r['closed']} trades | avg {avg:+.2f}% | total {total:+.2f}%"
        )
    return "\n".join(lines)


def _get_trades(n: int = 5) -> str:
    n = min(max(n, 1), 20)
    if not DB_PATH.exists():
        return "⚠️ No database yet."
    try:
        conn = _db()
        if not _table_exists(conn, "paper_trades"):
            conn.close()
            return "⚠️ No trades table yet."
        rows = conn.execute(
            "SELECT action, symbol, price, strategy, pnl_pct, timestamp "
            "FROM paper_trades ORDER BY timestamp DESC LIMIT ?", (n,)
        ).fetchall()
        conn.close()
    except Exception as e:
        return f"⚠️ DB error: {e}"

    if not rows:
        return "📭 No trades recorded yet."

    lines = [f"📋 *Last {n} Trades*"]
    for r in rows:
        ts  = (r["timestamp"] or "")[:16].replace("T", " ")
        pnl = f" | PnL: {r['pnl_pct']:+.2f}%" if r["pnl_pct"] is not None else ""
        act = "🟢 BUY" if r["action"] == "BUY" else "🔴 SELL"
        lines.append(
            f"{act} {r['symbol']} @ {r['price']:.4f} | {r['strategy'] or '?'}{pnl} | {ts}"
        )
    return "\n".join(lines)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id != CHAT_ID:
        return
    text = (
        "🤖 *AAATS Bot Commands*\n\n"
        "/status — system health & capital\n"
        "/positions — open positions\n"
        "/pnl — realized PnL by strategy\n"
        "/trades [N] — last N trades (max 20)\n"
        "/stop — activate kill switch (single-market, 24h)\n"
        "/killall — 🛑 EMERGENCY halt ALL markets (TOTP 2FA required)\n"
        "/help — this menu"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id != CHAT_ID:
        return
    await update.message.reply_text(_get_status(), parse_mode="Markdown")


async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id != CHAT_ID:
        return
    await update.message.reply_text(_get_positions(), parse_mode="Markdown")


async def cmd_pnl(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id != CHAT_ID:
        return
    await update.message.reply_text(_get_pnl(), parse_mode="Markdown")


async def cmd_trades(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id != CHAT_ID:
        return
    try:
        n = int(ctx.args[0]) if ctx.args else 5
    except (ValueError, IndexError):
        n = 5
    await update.message.reply_text(_get_trades(n), parse_mode="Markdown")


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id != CHAT_ID:
        return
    ctx.user_data["awaiting_stop_confirm"] = True
    await update.message.reply_text(
        "⚠️ *Kill Switch*\n\nReply with exactly:\n`CONFIRM STOP`\n\nThis will halt all trading for 24 hours.",
        parse_mode="Markdown",
    )


async def cmd_killall(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /killall — strongest kill command. Requires TOTP 2FA.

    Flow:
      1. User: /killall
      2. Bot:  asks for 6-digit TOTP code
      3. User: <6-digit code from authenticator app>
      4. Bot:  if valid → fires foundation.kill_switch.halt("all", ...)
                        + writes kill_switch.json (legacy fallback)
                        + replies HALTED
               if invalid → rejects + clears state

    Differences from /stop:
      - 2FA via TOTP (not just typing "CONFIRM STOP")
      - Halts ALL markets (crypto + india + us) via foundation.kill_switch
      - Sets up structured halt-state file the strategy loops actually read
      - Single-step reply (one message), faster in an emergency
    """
    if update.effective_chat.id != CHAT_ID:
        return

    if not KILLALL_TOTP_SECRET:
        await update.message.reply_text(
            "❌ /killall is not configured.\n\n"
            "Set `KILLALL_TOTP_SECRET` in .env "
            "(generate with `python -c 'import pyotp; print(pyotp.random_base32())'` "
            "and add to your authenticator app).",
            parse_mode="Markdown",
        )
        return

    ctx.user_data["awaiting_killall_totp"] = True
    await update.message.reply_text(
        "🛑 *KILLALL — 2FA required*\n\n"
        "Reply with the *current 6-digit code* from your authenticator app.\n\n"
        "This will:\n"
        "• Halt ALL markets via foundation.kill_switch\n"
        "• Block new orders system-wide\n"
        "• Require manual `emergency_resume.py` to re-enable\n\n"
        "_Code expires in ~30s. Send a fresh code if it fails._",
        parse_mode="Markdown",
    )


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.id != CHAT_ID:
        return

    text = update.message.text.strip()

    # ── /killall TOTP reply branch ─────────────────────────────────────────
    if ctx.user_data.get("awaiting_killall_totp"):
        ctx.user_data["awaiting_killall_totp"] = False

        if not KILLALL_TOTP_SECRET:
            await update.message.reply_text("❌ /killall not configured (no TOTP secret).")
            return

        # Validate TOTP — accept current code OR ±1 step (covers ~60s window
        # to forgive clock skew between phone, server, and message latency).
        try:
            import pyotp
            totp = pyotp.TOTP(KILLALL_TOTP_SECRET)
            if not totp.verify(text, valid_window=1):
                await update.message.reply_text(
                    "❌ Invalid TOTP code. /killall NOT executed. "
                    "Run /killall again with a fresh code if you still want to halt."
                )
                log.warning(
                    "killall TOTP failed | chat=%s | reply_len=%d",
                    update.effective_chat.id, len(text),
                )
                return
        except ImportError:
            await update.message.reply_text(
                "❌ pyotp library not installed in bot container. "
                "/killall cannot validate 2FA. Use SSH + emergency_halt.py."
            )
            return
        except Exception as exc:
            await update.message.reply_text(f"❌ TOTP validation error: {exc}")
            return

        # ── TOTP verified — execute halt ───────────────────────────────────
        try:
            # Path may differ between bot container and main container; we
            # need to call foundation.kill_switch in the main container.
            # Strategy: write halt_state.json directly so the main container
            # picks it up next cycle. Same file format foundation.kill_switch
            # uses (data/halt_state.json with {market: bool}).
            halt_path = Path("/app/data/halt_state.json")
            halt_path.parent.mkdir(parents=True, exist_ok=True)
            halt_path.write_text(
                json.dumps({"us": True, "india": True, "crypto": True}, indent=2)
            )

            # Belt-and-braces: also write the legacy kill_switch.json that
            # the old /stop command writes, so any loop reading either file
            # sees the halt.
            legacy_path = Path("/app/data/kill_switch.json")
            legacy_path.write_text(json.dumps({
                "active": True,
                "activated_at": datetime.now(timezone.utc).isoformat(),
                "reason": "telegram_killall_2fa",
                "duration_hours": 24,
                "all_markets": True,
            }))

            # Best-effort audit-trail entry (skipped if sqlite path is wrong
            # in the bot container — never block the halt).
            try:
                # Import lazy so missing modules in bot container don't break the bot.
                from foundation.audit_trail import AuditTrail
                AuditTrail(db_path="/app/data/audit_trail.db").append(
                    market="all",
                    module="telegram_killall",
                    event_type="HALT",
                    details={
                        "triggered_by": "telegram_/killall_2fa",
                        "chat_id": update.effective_chat.id,
                    },
                    result="HALTED",
                    reason="emergency_halt_via_telegram_with_2fa",
                )
            except Exception as exc:
                log.warning("killall audit entry skipped: %s", exc)

            await update.message.reply_text(
                "🛑 *KILLALL EXECUTED*\n\n"
                "All markets halted. New orders blocked.\n"
                "Trading loops will see this within ~1 cycle (≤15min).\n\n"
                "To resume: SSH to server, run\n"
                "`python scripts/emergency_resume.py --market all "
                "--authorized-by Puneeth --reason \"<reason>\"`",
                parse_mode="Markdown",
            )
            log.critical(
                "KILLALL executed via Telegram with valid 2FA | chat=%s",
                update.effective_chat.id,
            )
        except Exception as exc:
            await update.message.reply_text(f"❌ killall write failed: {exc}")
            log.error("killall execution failed: %s", exc)
        return

    # ── /stop CONFIRM STOP branch (existing) ───────────────────────────────
    if ctx.user_data.get("awaiting_stop_confirm"):
        if text == "CONFIRM STOP":
            ctx.user_data["awaiting_stop_confirm"] = False
            # Write kill switch file
            kill_path = Path("/app/data/kill_switch.json")
            kill_path.parent.mkdir(parents=True, exist_ok=True)
            kill_path.write_text(json.dumps({
                "active": True,
                "activated_at": datetime.now(timezone.utc).isoformat(),
                "reason": "telegram_command",
                "duration_hours": 24,
            }))
            await update.message.reply_text(
                "🛑 Kill switch ACTIVATED. Trading halted for 24 hours.\n"
                "Restart the container to clear.",
                parse_mode="Markdown",
            )
            log.warning("Kill switch activated via Telegram command")
        else:
            ctx.user_data["awaiting_stop_confirm"] = False
            await update.message.reply_text("Kill switch cancelled.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not TOKEN:
        log.error("ALERTS__TELEGRAM_BOT_TOKEN not set — exiting")
        return
    if not CHAT_ID:
        log.error("ALERTS__TELEGRAM_CHAT_ID not set — exiting")
        return

    log.info("Starting AAATS Telegram bot (polling)...")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("start",     cmd_help))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("pnl",       cmd_pnl))
    app.add_handler(CommandHandler("trades",    cmd_trades))
    app.add_handler(CommandHandler("stop",      cmd_stop))
    app.add_handler(CommandHandler("killall",   cmd_killall))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot running. Polling for commands...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
