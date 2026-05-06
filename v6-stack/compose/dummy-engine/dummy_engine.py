"""
AAATS v6 — Dummy engine (Phase ε scaffolding).

Models the heartbeat + work pattern of the real engine without doing any
trading. Exists to validate the watchdog's self-healing behaviour against
the 5 induced-failure tests (IS Phase 4) before any real engine code runs.

Two asyncio tasks per FAD §4.2:
  - work_loop:      simulates cycles
  - heartbeat_loop: writes aaats:hb:engine every 30s (TTL 90s),
                    INDEPENDENT of work — proves the loop is responsive
  - healthchecks_loop: pings Healthchecks.io if HEALTHCHECKS_URL is set

Exposes /metrics on :9100 in Prometheus text format and /ready for liveness.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from contextlib import suppress
from datetime import datetime, timezone

import redis.asyncio as aioredis
from aiohttp import ClientSession, ClientTimeout, web

LOG = logging.getLogger("dummy_engine")

REDIS_HOST = os.environ.get("REDIS_HOST", "aaats-redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD_FILE = os.environ.get("REDIS_PASSWORD_FILE", "/run/secrets/redis_password")

HB_KEY           = os.environ.get("ENGINE_HB_KEY", "aaats:hb:engine")
HB_INTERVAL_S    = int(os.environ.get("ENGINE_HB_INTERVAL_S", "30"))
HB_TTL_S         = int(os.environ.get("ENGINE_HB_TTL_S", "90"))
HB_WRITE_TIMEOUT = float(os.environ.get("ENGINE_HB_WRITE_TIMEOUT_S", "5.0"))
WORK_INTERVAL_S  = int(os.environ.get("ENGINE_WORK_INTERVAL_S", "5"))
HEALTHCHECKS_URL = os.environ.get("HEALTHCHECKS_URL", "")
HEALTHCHECKS_INTERVAL_S = int(os.environ.get("HEALTHCHECKS_INTERVAL_S", "60"))

METRICS_PORT = int(os.environ.get("METRICS_PORT", "9100"))


_metrics = {
    "cycles_total": 0,
    "heartbeats_total": 0,
    "heartbeats_failed_total": 0,
    "healthchecks_pings_total": 0,
    "healthchecks_pings_failed_total": 0,
    "process_start_time_seconds": datetime.now(timezone.utc).timestamp(),
}


def _read_password() -> str:
    return open(REDIS_PASSWORD_FILE, "r", encoding="utf-8").read().strip()


async def _heartbeat_loop(r: aioredis.Redis, stop: asyncio.Event) -> None:
    """Independent heartbeat task — writes regardless of work_loop state."""
    cycle_id = 0
    while not stop.is_set():
        cycle_id += 1
        ts = datetime.now(timezone.utc).timestamp()
        value = f"{ts:.3f}:{cycle_id}:OK"
        try:
            await asyncio.wait_for(
                r.set(HB_KEY, value, ex=HB_TTL_S),
                timeout=HB_WRITE_TIMEOUT,
            )
            _metrics["heartbeats_total"] += 1
            LOG.debug("HB %s → %s", HB_KEY, value)
        except asyncio.TimeoutError:
            _metrics["heartbeats_failed_total"] += 1
            LOG.warning("HB write timeout (>%.1fs)", HB_WRITE_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            _metrics["heartbeats_failed_total"] += 1
            LOG.warning("HB write failed: %s", e)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=HB_INTERVAL_S)


async def _work_loop(stop: asyncio.Event) -> None:
    """Simulates the engine's work — placeholder for the real trading loop."""
    cycle = 0
    while not stop.is_set():
        cycle += 1
        _metrics["cycles_total"] = cycle
        LOG.info("dummy cycle %d", cycle)
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=WORK_INTERVAL_S)


async def _healthchecks_loop(stop: asyncio.Event) -> None:
    if not HEALTHCHECKS_URL:
        LOG.info("HEALTHCHECKS_URL not set; skipping out-of-process pings")
        return
    timeout = ClientTimeout(total=10)
    async with ClientSession(timeout=timeout) as session:
        while not stop.is_set():
            try:
                async with session.get(HEALTHCHECKS_URL) as resp:
                    if 200 <= resp.status < 300:
                        _metrics["healthchecks_pings_total"] += 1
                    else:
                        _metrics["healthchecks_pings_failed_total"] += 1
                        LOG.warning("Healthchecks.io returned HTTP %d", resp.status)
            except Exception as e:  # noqa: BLE001
                _metrics["healthchecks_pings_failed_total"] += 1
                LOG.warning("Healthchecks.io ping failed: %s", e)
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=HEALTHCHECKS_INTERVAL_S)


async def _metrics_handler(_request: web.Request) -> web.Response:
    lines = []
    for name, kind, help_text in [
        ("dummy_engine_cycles_total",                  "counter", "Total work cycles."),
        ("dummy_engine_heartbeats_total",              "counter", "Total heartbeats written."),
        ("dummy_engine_heartbeats_failed_total",       "counter", "Total heartbeat write failures."),
        ("dummy_engine_healthchecks_pings_total",      "counter", "Healthchecks.io successful pings."),
        ("dummy_engine_healthchecks_pings_failed_total", "counter", "Healthchecks.io failed pings."),
        ("process_start_time_seconds",                 "gauge",   "UNIX time when the process started."),
    ]:
        key = name.replace("dummy_engine_", "") if name.startswith("dummy_engine_") else name
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        lines.append(f"{name} {_metrics[key]}")
    body = "\n".join(lines) + "\n"
    return web.Response(text=body, content_type="text/plain", charset="utf-8")


async def _ready_handler(_request: web.Request) -> web.Response:
    return web.Response(text="ok\n", content_type="text/plain")


async def main() -> int:
    logging.basicConfig(
        level=os.environ.get("ENGINE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    pwd = _read_password()
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=pwd, socket_timeout=5)
    await r.ping()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for s in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(s, lambda sig=s: (LOG.info("signal %s received", sig), stop.set()))

    app = web.Application()
    app.router.add_get("/metrics", _metrics_handler)
    app.router.add_get("/ready",   _ready_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", METRICS_PORT)
    await site.start()
    LOG.info("metrics server on :%d", METRICS_PORT)

    LOG.info(
        "dummy_engine up. hb=%s interval=%ds ttl=%ds work=%ds hc.io=%s",
        HB_KEY, HB_INTERVAL_S, HB_TTL_S, WORK_INTERVAL_S, bool(HEALTHCHECKS_URL),
    )

    tasks = [
        asyncio.create_task(_heartbeat_loop(r, stop),    name="heartbeat"),
        asyncio.create_task(_work_loop(stop),            name="work"),
        asyncio.create_task(_healthchecks_loop(stop),    name="healthchecks"),
    ]
    await stop.wait()

    LOG.info("draining tasks")
    for t in tasks:
        t.cancel()
        with suppress(asyncio.CancelledError):
            await t

    await runner.cleanup()
    with suppress(Exception):
        await r.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
