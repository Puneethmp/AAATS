"""Redis wrapper + namespace registry.

Async-only. Wraps redis.asyncio with a typed surface and central key-namespace
registry. Risk-critical reads MUST NOT use this module directly — they go via
storage.dao.* `read_durable_*` paths to Postgres.

Public surface:
    init_redis(url=None) → aioredis.Redis
    close_redis()        → None
    get_redis()          → aioredis.Redis  (raises if not init)
    KEYS                 → namespace registry (constants)

Design rules:
  - Every key starts with `aaats:`.
  - All ephemeral keys carry a TTL.
  - Caches are `aaats:cache:*` (clearly read-only for risk).
  - Heartbeats and live state are TTL-bounded (90s, 10s).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import redis.asyncio as aioredis

LOG = logging.getLogger("storage.redis")

_redis: Optional[aioredis.Redis] = None


def _read_password_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


async def init_redis(
    url: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    password_file: Optional[str] = None,
    socket_timeout: float = 30.0,
) -> aioredis.Redis:
    """Initialise the global async client (idempotent)."""
    global _redis
    if _redis is not None:
        return _redis
    if url is None:
        host = host or os.environ.get("REDIS_HOST", "aaats-redis")
        port = port or int(os.environ.get("REDIS_PORT", "6379"))
        pwd = ""
        pwd_file = password_file or os.environ.get("REDIS_PASSWORD_FILE",
                                                     "/run/secrets/redis_password")
        if pwd_file:
            pwd = _read_password_file(pwd_file)
        _redis = aioredis.Redis(
            host=host, port=port, password=pwd,
            socket_timeout=socket_timeout, socket_keepalive=True,
        )
    else:
        _redis = aioredis.from_url(url, socket_timeout=socket_timeout, socket_keepalive=True)
    await _redis.ping()
    LOG.info("redis client ready")
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception as e:  # noqa: BLE001
            LOG.warning("redis aclose failed: %s", e)
        _redis = None


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("redis client not initialised — call init_redis() first")
    return _redis


# =============================================================================
# Key namespace registry — single source of truth for every Redis key the
# v6 substrate uses. Adding a new key requires updating this table.
# =============================================================================

class KEYS:
    # Heartbeats (TTL 90s)
    HB_ENGINE                  = "aaats:hb:engine"
    HB_ENGINE_FOR              = "aaats:hb:engine:{market}"
    HB_WATCHDOG                = "aaats:hb:watchdog"
    HB_WS_FOR                  = "aaats:hb:ws:{market}"          # FAD §4.3 future use

    # Control plane
    HALT_REQUESTED             = "aaats:halt:requested"
    RESTART_REQUESTED          = "aaats:restart:requested"
    KILL_PENDING_FOR           = "aaats:kill_pending:{chat_id}"
    MODE                       = "aaats:mode"                    # cache; CST in Postgres

    # Alerts
    ALERTS_QUEUE               = "aaats:alerts:queue"
    BOT_LAST_DIGEST_DATE       = "aaats:bot:last_digest_date"

    # Metrics counters
    METRICS_AUTO_RESTARTS      = "aaats:metrics:auto_restarts"

    # Risk peaks (cache only — durable truth in aaats.risk_peaks Postgres table)
    CACHE_RISK_PEAK_PORTFOLIO  = "aaats:cache:risk:peak:portfolio"
    CACHE_RISK_PEAK_FOR        = "aaats:cache:risk:peak:{market}"

    # Position cache (read-only for dashboards/bot; risk does not consult)
    CACHE_POSITIONS_FOR        = "aaats:cache:positions:{market}"
    CACHE_STATE_FOR            = "aaats:cache:state:{market}"

    # Token buckets (FAD §4.5)
    BUCKET_EXCHANGE            = "aaats:bucket:exchange"
    BUCKET_ANTHROPIC           = "aaats:bucket:anthropic"
    BUCKET_TELEGRAM            = "aaats:bucket:telegram"

    # Semantic cache (FAD §4.8) — TTL 12h
    CACHE_SEMANTIC_FOR         = "aaats:cache:semantic:{hash}"
