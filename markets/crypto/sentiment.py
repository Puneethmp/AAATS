"""
markets/crypto/sentiment.py  —  Sentiment overlay (2026-05-12)
==============================================================

PURPOSE
-------
Cheap, always-on sentiment gate for crypto strategies. Primary signal:
Fear & Greed Index (alternative.me, free, no API key). Used as a regime-
flavor multiplier on top of price/structure signals.

Existing system: live_paper_runner already gates the ensemble loop on F&G
(line 1146). But C3 and C6 bypass the ensemble — they need their own gate.

USAGE
-----
    from markets.crypto.sentiment import (
        get_fear_greed, should_skip_c6_on_sentiment, sentiment_size_multiplier,
    )

    fg = get_fear_greed()
    if should_skip_c6_on_sentiment(fg):
        return  # extreme-greed top — mean reversion thesis fails

    size_mult = sentiment_size_multiplier(fg, strategy="c3")
    trade_usd = base_size * size_mult
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
# F&G is a 0–100 score where lower = more fear.
EXTREME_FEAR_MAX     = 25   # below this = extreme fear
GREED_MIN            = 60   # 60-75 = greed
EXTREME_GREED_MIN    = 75   # 75+ = extreme greed (market top zone)

# Refresh cadence — F&G updates once per day. 1h cache is fine.
CACHE_TTL_SECONDS    = 3600

_cache: dict[str, Any] = {"ts": 0.0, "score": None, "classification": None}


# ── Fetcher ───────────────────────────────────────────────────────────────────
def get_fear_greed(force_refresh: bool = False) -> int | None:
    """
    Return the current Fear & Greed score (0-100) or None if unavailable.
    Free public API: https://api.alternative.me/fng/
    """
    now = time.time()
    if (not force_refresh
        and _cache["score"] is not None
        and (now - _cache["ts"]) < CACHE_TTL_SECONDS):
        return _cache["score"]

    try:
        import urllib.request
        import json
        with urllib.request.urlopen(
            "https://api.alternative.me/fng/?limit=1", timeout=8
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        entry = data.get("data", [{}])[0]
        score = int(entry.get("value", 0))
        cls   = entry.get("value_classification", "")
        _cache["ts"] = now
        _cache["score"] = score
        _cache["classification"] = cls
        log.info("[sentiment] F&G=%d (%s)", score, cls)
        return score
    except Exception as exc:
        log.warning("[sentiment] F&G fetch failed: %s — treating as neutral", exc)
        return None


# ── Gates ─────────────────────────────────────────────────────────────────────
def should_skip_c6_on_sentiment(fg_score: int | None = None) -> bool:
    """
    Skip C6 (Bollinger range mean reversion) when market is in extreme greed.
    Rationale: euphoria distorts %B mechanics — even "oversold" levels are
    sucker bounces. Wait for sentiment to normalize.
    """
    fg = fg_score if fg_score is not None else get_fear_greed()
    if fg is None:
        return False  # data unavailable → don't block; fail open
    if fg >= EXTREME_GREED_MIN:
        log.info("[sentiment] F&G=%d ≥ %d (extreme greed) — SKIP C6 entries",
                 fg, EXTREME_GREED_MIN)
        return True
    return False


def should_skip_c3_on_sentiment(fg_score: int | None = None) -> bool:
    """
    Skip C3 when market is in extreme greed AND BTC near top.
    Less aggressive than C6 skip — C3 is alt/BTC ratio, less tied to absolute
    sentiment. Only block in the worst conditions.
    """
    fg = fg_score if fg_score is not None else get_fear_greed()
    if fg is None:
        return False
    if fg >= 85:   # extreme-extreme greed only
        log.info("[sentiment] F&G=%d ≥ 85 (euphoria) — SKIP C3 entries", fg)
        return True
    return False


def sentiment_size_multiplier(fg_score: int | None = None,
                              strategy: str = "default") -> float:
    """
    Return a size multiplier (0.0 to 1.3) based on current sentiment.

    Mean reversion edges are FATTER in extreme fear and THINNER in greed.
    So scale C3/C6 position sizes accordingly:

        F&G 0-25  (extreme fear)   →  1.30  (juicy oversold setups)
        F&G 25-45 (fear)           →  1.10
        F&G 45-60 (neutral)        →  1.00
        F&G 60-75 (greed)          →  0.70
        F&G 75-85 (extreme greed)  →  0.40  (thin, dangerous, but allowed)
        F&G 85+   (euphoria)       →  0.0   (don't trade reversion in euphoria)
    """
    fg = fg_score if fg_score is not None else get_fear_greed()
    if fg is None:
        return 1.0   # neutral when data unavailable

    if fg < EXTREME_FEAR_MAX:
        return 1.30
    elif fg < 45:
        return 1.10
    elif fg < GREED_MIN:
        return 1.00
    elif fg < EXTREME_GREED_MIN:
        return 0.70
    elif fg < 85:
        return 0.40
    else:
        return 0.0


def current_classification() -> str:
    """Return the human-readable F&G classification: 'Fear', 'Neutral', etc."""
    return _cache.get("classification") or "Unknown"
