"""
AAATS v6 — Watchdog sidecar (Phase ε scaffolding).

Polls a Redis key written by the engine. If it is missing or stale beyond
a configured threshold, kills the engine container and starts a fresh one.

Properties:
- Restart cooldown (default 300s) prevents tight kill loops (RR R-07).
- Allowlist on target container names — refuses to act on anything else.
- Soft-fail on transient Redis/Docker errors; logs and retries next cycle.
- Emits its own heartbeat (`aaats:hb:watchdog`) so an outer monitor (or
  Healthchecks.io) can detect a frozen watchdog.
- Writes JSON alerts to a Redis list (`aaats:alerts:queue`), consumed by
  the Telegram bot (Phase ζ).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import docker
import redis

LOG = logging.getLogger("watchdog")

# Tunables — env-overridable for failure tests.
ENGINE_CONTAINER = os.environ.get("WATCHDOG_TARGET_CONTAINER", "aaats-engine")
HB_KEY           = os.environ.get("WATCHDOG_HB_KEY", "aaats:hb:engine")
WATCHDOG_HB_KEY  = os.environ.get("WATCHDOG_OWN_HB_KEY", "aaats:hb:watchdog")
ALERT_LIST       = os.environ.get("WATCHDOG_ALERT_LIST", "aaats:alerts:queue")
RESTART_COUNTER  = os.environ.get("WATCHDOG_RESTART_COUNTER", "aaats:metrics:auto_restarts")
POLL_SECONDS     = int(os.environ.get("WATCHDOG_POLL_SECONDS", "30"))
HB_STALE_SECONDS = int(os.environ.get("WATCHDOG_HB_STALE_SECONDS", "90"))
COOLDOWN_SECONDS = int(os.environ.get("WATCHDOG_COOLDOWN_SECONDS", "300"))
ALERT_LIST_CAP   = int(os.environ.get("WATCHDOG_ALERT_LIST_CAP", "1000"))
# Require this many consecutive stale/missing observations before acting.
# Tolerates single-poll anomalies — Redis bounce, AOF replay glitch, engine
# reconnect window — without restarting a likely-healthy engine.
STALE_CONFIRMATIONS = int(os.environ.get("WATCHDOG_STALE_CONFIRMATIONS", "2"))

REDIS_HOST = os.environ.get("REDIS_HOST", "aaats-redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD_FILE = os.environ.get("REDIS_PASSWORD_FILE", "/run/secrets/redis_password")

# Defense in depth: only these container names may be killed/started.
TARGET_ALLOWLIST = frozenset(
    name.strip() for name in os.environ.get(
        "WATCHDOG_ALLOWLIST",
        "aaats-engine,aaats-engine-us,aaats-engine-india,aaats-engine-crypto",
    ).split(",")
    if name.strip()
)


def _read_password() -> str:
    try:
        return open(REDIS_PASSWORD_FILE, "r", encoding="utf-8").read().strip()
    except OSError as e:
        LOG.error("Cannot read redis password from %s: %s", REDIS_PASSWORD_FILE, e)
        sys.exit(2)


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _emit_alert(
    r: redis.Redis,
    *,
    level: str,
    channel: str,
    code: str,
    title: str,
    message: str,
    fields: Optional[dict] = None,
) -> None:
    """Push an alert to the queue using the v6 alert schema.

    See TELEGRAM_BOT_ARCHITECTURE.md §4 for the schema.
    """
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "watchdog",
        "level": level,
        "channel": channel,
        "code": code,
        "title": title,
        "message": message,
        "fields": fields or {},
    }
    try:
        r.lpush(ALERT_LIST, json.dumps(payload))
        r.ltrim(ALERT_LIST, 0, ALERT_LIST_CAP - 1)
    except redis.RedisError as e:
        LOG.error("Alert push to %s failed: %s", ALERT_LIST, e)


def _emit_own_heartbeat(r: redis.Redis, status: str = "ALIVE") -> None:
    try:
        r.set(WATCHDOG_HB_KEY, f"{_now_ts():.3f}:{status}", ex=POLL_SECONDS * 3)
    except redis.RedisError as e:
        LOG.warning("Own heartbeat write failed: %s", e)


def _hb_age(r: redis.Redis) -> Optional[float]:
    try:
        val = r.get(HB_KEY)
    except redis.RedisError as e:
        LOG.error("Redis GET %s failed: %s", HB_KEY, e)
        return None
    if val is None:
        return None
    try:
        ts = float(val.decode("utf-8").split(":", 1)[0])
        return _now_ts() - ts
    except (ValueError, UnicodeDecodeError) as e:
        LOG.error("Malformed heartbeat value %r: %s", val, e)
        return None


def _restart_engine(d: docker.DockerClient, container_name: str) -> bool:
    if container_name not in TARGET_ALLOWLIST:
        LOG.error("REFUSE: %s not in allowlist %s", container_name, sorted(TARGET_ALLOWLIST))
        return False
    try:
        c = d.containers.get(container_name)
    except docker.errors.NotFound:
        LOG.error("Target container %s not found", container_name)
        return False
    try:
        LOG.warning("Killing %s", container_name)
        c.kill()
    except docker.errors.APIError as e:
        # 409 if already stopped — that's fine.
        LOG.warning("kill returned %s (may already be stopped)", e)
    try:
        c = d.containers.get(container_name)  # refresh state
        LOG.warning("Starting %s", container_name)
        c.start()
        return True
    except docker.errors.APIError as e:
        LOG.error("Start failed: %s", e)
        return False


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("WATCHDOG_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    pwd = _read_password()
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=pwd, socket_timeout=5)
    try:
        r.ping()
    except redis.RedisError as e:
        LOG.error("Redis unreachable at %s:%s: %s", REDIS_HOST, REDIS_PORT, e)
        return 2

    d = docker.from_env()
    try:
        d.ping()
    except docker.errors.DockerException as e:
        LOG.error("Docker daemon unreachable: %s", e)
        return 3

    LOG.info(
        "watchdog up. target=%s hb_key=%s stale=%ds confirmations=%d cooldown=%ds poll=%ds allowlist=%s",
        ENGINE_CONTAINER, HB_KEY, HB_STALE_SECONDS, STALE_CONFIRMATIONS,
        COOLDOWN_SECONDS, POLL_SECONDS, sorted(TARGET_ALLOWLIST),
    )
    _emit_alert(
        r, level="P2", channel="SYSTEM", code="watchdog_started",
        title="Watchdog online",
        message=f"target={ENGINE_CONTAINER}",
        fields={
            "target": ENGINE_CONTAINER,
            "stale_threshold_s": HB_STALE_SECONDS,
            "poll_s": POLL_SECONDS,
            "cooldown_s": COOLDOWN_SECONDS,
        },
    )

    last_restart_at = 0.0
    stale_streak = 0
    stop = {"flag": False}

    def _on_signal(signum, _frame):
        LOG.info("signal %s received", signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    while not stop["flag"]:
        _emit_own_heartbeat(r)

        # Distinguish "redis unreachable" from "engine heartbeat missing".
        # If redis itself is down we must NOT kill a healthy engine.
        try:
            r.ping()
        except redis.RedisError as e:
            LOG.error("redis unreachable: %s — skipping this iteration", e)
            for _ in range(POLL_SECONDS):
                if stop["flag"]:
                    break
                time.sleep(1)
            continue

        age = _hb_age(r)

        if age is None:
            stale_streak += 1
            LOG.warning("no heartbeat at %s (streak=%d/%d)", HB_KEY, stale_streak, STALE_CONFIRMATIONS)
        elif age > HB_STALE_SECONDS:
            stale_streak += 1
            LOG.warning(
                "heartbeat stale (age=%.1fs > %ds, streak=%d/%d)",
                age, HB_STALE_SECONDS, stale_streak, STALE_CONFIRMATIONS,
            )
        else:
            if stale_streak:
                LOG.info("heartbeat recovered (age=%.1fs); resetting stale streak", age)
            stale_streak = 0

        if stale_streak >= STALE_CONFIRMATIONS:
            now = _now_ts()
            since = now - last_restart_at
            if since < COOLDOWN_SECONDS:
                LOG.info(
                    "cooldown active: %ds since last restart < %ds — not acting",
                    int(since), COOLDOWN_SECONDS,
                )
            else:
                _emit_alert(
                    r, level="P1", channel="CRITICAL", code="engine_stalled_restart",
                    title="Engine restarted",
                    message=f"heartbeat stale across {stale_streak} polls; restarting {ENGINE_CONTAINER}",
                    fields={
                        "container": ENGINE_CONTAINER,
                        "stale_streak": stale_streak,
                        "threshold_s": HB_STALE_SECONDS,
                        "hb_age_s": (round(age, 1) if age is not None else "n/a"),
                    },
                )
                if _restart_engine(d, ENGINE_CONTAINER):
                    last_restart_at = now
                    stale_streak = 0  # reset; engine should write fresh HB now
                    try:
                        r.incr(RESTART_COUNTER)
                    except redis.RedisError:
                        pass
                else:
                    _emit_alert(
                        r, level="P0", channel="CRITICAL", code="engine_restart_failed",
                        title="Engine restart FAILED",
                        message=f"docker SDK failed to restart {ENGINE_CONTAINER}; manual intervention required",
                        fields={"container": ENGINE_CONTAINER},
                    )

        # Sleep with shutdown responsiveness (1-second granularity).
        for _ in range(POLL_SECONDS):
            if stop["flag"]:
                break
            time.sleep(1)

    _emit_alert(
        r, level="P2", channel="SYSTEM", code="watchdog_stopping",
        title="Watchdog shutting down",
        message="received shutdown signal",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
