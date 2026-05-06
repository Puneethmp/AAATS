"""
AAATS v6 engine wrapper.

Shape mirrors the dummy engine (heartbeat + /metrics + /ready) so the watchdog
config and Prometheus scrape target stay identical at cutover. The work loop
calls trading.live_paper_runner.main() once per cycle (default 1h).

Three asyncio tasks:
  - heartbeat_loop:  SET aaats:hb:engine ex=90 every 30s — independent of work
  - work_loop:       calls live_paper_runner.main() every WORK_INTERVAL_S
  - http_server:     /metrics (Prometheus text) + /ready on :9100

Critical: the redis_alerts shim is wired in BEFORE importing the runner so any
send_alert calls inside the trading code go to Redis instead of trying to call
python-telegram-bot directly (which would no-op without OS env credentials).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as aioredis
from aiohttp import web

# ── monkey-patch send_alert BEFORE anything imports observability.alerts ──────
from engine import redis_alerts as _redis_alerts          # noqa: E402

import observability.alerts as _legacy_alerts             # noqa: E402
_legacy_alerts.send_alert = _redis_alerts.send_alert      # redirect to redis

# ── now safe to import the runner ─────────────────────────────────────────────
from trading import live_paper_runner                     # noqa: E402


# Pin cycle count off the runner's own "Cycle #N done" log line so the wrapper's
# /metrics output stays accurate now that main() self-loops inside its thread
# (the previous "increment after main() returns" never fires).
class _CycleCounter(logging.Handler):
    _prev_monotonic: float | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if "Cycle #" in msg and "done" in msg:
                _metrics["cycles_total"] += 1
                now = time.monotonic()
                if self._prev_monotonic is not None:
                    _metrics["last_cycle_seconds"] = now - self._prev_monotonic
                self._prev_monotonic = now
        except Exception:  # noqa: BLE001
            pass


logging.getLogger("paper_runner").addHandler(_CycleCounter())

# ── config ────────────────────────────────────────────────────────────────────
LOG = logging.getLogger("v6_engine")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
)

REDIS_HOST          = os.environ.get("REDIS_HOST", "aaats-redis")
REDIS_PORT          = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD_FILE = os.environ.get("REDIS_PASSWORD_FILE", "/run/secrets/redis_password")

HB_KEY        = os.environ.get("ENGINE_HB_KEY", "aaats:hb:engine")
HB_INTERVAL_S = int(os.environ.get("ENGINE_HB_INTERVAL_S", "30"))
HB_TTL_S      = int(os.environ.get("ENGINE_HB_TTL_S", "90"))
HB_TIMEOUT_S  = float(os.environ.get("ENGINE_HB_WRITE_TIMEOUT_S", "5.0"))

# 1 cycle/hour matches the runner's hourly Task Scheduler design (NSE + crypto).
WORK_INTERVAL_S = int(os.environ.get("ENGINE_WORK_INTERVAL_S", "3600"))

METRICS_PORT  = int(os.environ.get("METRICS_PORT", "9100"))


_metrics = {
    "cycles_total":             0,
    "cycles_failed_total":      0,
    "heartbeats_total":         0,
    "heartbeats_failed_total":  0,
    "last_cycle_seconds":       0.0,
    "process_start_time_seconds": datetime.now(timezone.utc).timestamp(),
}


def _read_password() -> str:
    try:
        with open(REDIS_PASSWORD_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return os.environ.get("REDIS_PASSWORD", "")


# ── tasks ─────────────────────────────────────────────────────────────────────

async def heartbeat_loop(r: aioredis.Redis, stop: asyncio.Event) -> None:
    cycle = 0
    while not stop.is_set():
        cycle += 1
        ts = datetime.now(timezone.utc).timestamp()
        try:
            await asyncio.wait_for(
                r.set(HB_KEY, f"{ts:.3f}:{cycle}:OK", ex=HB_TTL_S),
                timeout=HB_TIMEOUT_S,
            )
            _metrics["heartbeats_total"] += 1
        except Exception as e:  # noqa: BLE001
            _metrics["heartbeats_failed_total"] += 1
            LOG.warning("heartbeat write failed: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=HB_INTERVAL_S)
        except asyncio.TimeoutError:
            pass


async def work_loop(stop: asyncio.Event) -> None:
    """Run live_paper_runner.main() in a thread; sleep WORK_INTERVAL_S between cycles."""
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            await asyncio.to_thread(live_paper_runner.main)
            _metrics["cycles_total"] += 1
        except Exception as e:  # noqa: BLE001
            _metrics["cycles_failed_total"] += 1
            LOG.exception("work cycle failed: %s", e)
            _redis_alerts.send_alert(
                f"❌ engine cycle error: {e}", market="system"
            )
        _metrics["last_cycle_seconds"] = time.monotonic() - t0
        try:
            await asyncio.wait_for(stop.wait(), timeout=WORK_INTERVAL_S)
        except asyncio.TimeoutError:
            pass


# ── http server: /metrics + /ready ────────────────────────────────────────────

_DATA_DIR = Path(os.environ.get("ENGINE_DATA_DIR", "/app/data"))


def _read_json_safe(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _live_state_lines() -> list[str]:
    """Read paper_portfolio.json + paper_positions.json + stat_arb_state.json on
    each scrape and emit one labelled metric per market — capital, realized PnL,
    trade counts, win rate, open position count (includes stat-arb legs)."""
    out: list[str] = []
    portfolio  = _read_json_safe(_DATA_DIR / "paper_portfolio.json")
    positions  = _read_json_safe(_DATA_DIR / "paper_positions.json")
    stat_arb   = _read_json_safe(_DATA_DIR / "stat_arb_state.json")
    # Crypto pairs use "/" in the key (e.g. "BTC/USDT_ETH/USDT"); India pairs don't.
    stat_arb_crypto = sum(1 for k in stat_arb if isinstance(stat_arb.get(k), dict) and "/" in k)
    stat_arb_india  = sum(1 for k in stat_arb if isinstance(stat_arb.get(k), dict) and "/" not in k)
    for market in ("india", "crypto"):
        p = portfolio.get(market, {}) if isinstance(portfolio, dict) else {}
        cap   = float(p.get("capital", 0.0) or 0.0)
        rpnl  = float(p.get("realized_pnl", 0.0) or 0.0)
        trades = int(p.get("total_trades", 0) or 0)
        wins   = int(p.get("wins", 0) or 0)
        losses = int(p.get("losses", 0) or 0)
        win_rate = (wins / trades) if trades > 0 else 0.0
        open_count = len(positions.get(market, {})) if isinstance(positions, dict) else 0
        if market == "crypto":
            open_count += stat_arb_crypto
        elif market == "india":
            open_count += stat_arb_india
        lbl = f'{{market="{market}"}}'
        out.append(f"aaats_engine_capital{lbl} {cap}")
        out.append(f"aaats_engine_realized_pnl{lbl} {rpnl}")
        out.append(f"aaats_engine_total_trades{lbl} {trades}")
        out.append(f"aaats_engine_wins{lbl} {wins}")
        out.append(f"aaats_engine_losses{lbl} {losses}")
        out.append(f"aaats_engine_win_rate{lbl} {win_rate}")
        out.append(f"aaats_engine_open_positions{lbl} {open_count}")
    return out


async def metrics_handler(_: web.Request) -> web.Response:
    lines = []
    for name, value in _metrics.items():
        kind = "gauge" if name in ("last_cycle_seconds", "process_start_time_seconds") else "counter"
        lines.append(f"# TYPE aaats_engine_{name} {kind}")
        lines.append(f"aaats_engine_{name} {value}")

    # Live trading state — refreshed each scrape so Grafana sees fresh values
    lines.append("# TYPE aaats_engine_capital gauge")
    lines.append("# TYPE aaats_engine_realized_pnl gauge")
    lines.append("# TYPE aaats_engine_total_trades counter")
    lines.append("# TYPE aaats_engine_wins counter")
    lines.append("# TYPE aaats_engine_losses counter")
    lines.append("# TYPE aaats_engine_win_rate gauge")
    lines.append("# TYPE aaats_engine_open_positions gauge")
    lines.extend(_live_state_lines())

    # Back-compat aliases — keep dummy-engine metric names so existing
    # dashboards / Prometheus rules resolve without edits.
    aliases = {
        "dummy_engine_cycles_total":            _metrics["cycles_total"],
        "dummy_engine_heartbeats_total":        _metrics["heartbeats_total"],
        "dummy_engine_heartbeats_failed_total": _metrics["heartbeats_failed_total"],
        "process_start_time_seconds":           _metrics["process_start_time_seconds"],
    }
    for name, value in aliases.items():
        lines.append(f"# TYPE {name} counter")
        lines.append(f"{name} {value}")
    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")


async def ready_handler(_: web.Request) -> web.Response:
    return web.Response(text="ready\n", content_type="text/plain")


async def run_http(stop: asyncio.Event) -> None:
    app = web.Application()
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/ready", ready_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", METRICS_PORT)
    await site.start()
    LOG.info("http server on :%d (/metrics, /ready)", METRICS_PORT)
    await stop.wait()
    await runner.cleanup()


# ── main ──────────────────────────────────────────────────────────────────────

async def amain() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    r = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        password=_read_password() or None,
        decode_responses=True,
        socket_connect_timeout=3,
    )

    LOG.info(
        "v6 engine starting: redis=%s:%d hb_key=%s work_interval_s=%d metrics_port=%d",
        REDIS_HOST, REDIS_PORT, HB_KEY, WORK_INTERVAL_S, METRICS_PORT,
    )

    try:
        await asyncio.gather(
            heartbeat_loop(r, stop),
            work_loop(stop),
            run_http(stop),
        )
    finally:
        with suppress(Exception):
            await r.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()) or 0)
