"""
markets/crypto/universe.py  —  Dynamic Binance spot universe scanner
====================================================================

PURPOSE
-------
Replaces the hardcoded 6-symbol CRYPTO_SYMBOLS list with a daily-refreshed,
liquidity-filtered top-N universe. Strategies (C3 mean-reversion, C6
Bollinger range) get fed the live universe and decide which to trade.

USAGE
-----
    from markets.crypto.universe import get_liquid_universe

    symbols = get_liquid_universe(top_n=50)
    # → ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'DOGE/USDT', 'XRP/USDT', ...]
    # already filtered for liquidity, age, and spread.

DESIGN
------
- Single shared in-process cache; default TTL = 1 hour (universe is stable
  intra-cycle; refreshing every cycle would be wasteful).
- Result: list of symbol strings in Binance CCXT format ("BTC/USDT").
- Fail-safe: on any error, returns the FALLBACK list so strategies never
  see an empty universe and silently sit out.

FILTERS APPLIED (in order, hard rejection)
------------------------------------------
1. Symbol must end in "/USDT"   (no USDC/BUSD/EUR — single quote currency)
2. Must NOT be a stablecoin     (excludes USDC, FDUSD, TUSD, DAI, ...)
3. Must NOT be a leveraged token (excludes BTCUP, ETHDOWN, 3LBTC, ...)
4. 24h quote volume >= MIN_VOLUME_USD   (default $5,000,000)
5. Bid-ask spread <= MAX_SPREAD_PCT     (default 0.15% of mid)
6. Last trade price > $0.00001          (filter dust)

Then sort by 24h volume descending and take top N.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import time
from typing import Any

log = logging.getLogger(__name__)

# ── Disk cache (2026-05-13 — fix restart warmup tax) ──────────────────────────
# Without disk cache, every container restart triggers a fresh fetch_tickers()
# call (~500 symbols, 5-30s). With disk cache + 1h TTL the post-restart cycle
# resumes immediately if the persisted universe is still fresh.
_DISK_CACHE_FILE = pathlib.Path(
    os.environ.get("AAATS_UNIVERSE_CACHE", "/app/data/universe_cache.json")
)


# ── Filters ───────────────────────────────────────────────────────────────────
MIN_VOLUME_USD     = 5_000_000   # 24h quote volume floor
MAX_SPREAD_PCT     = 0.0015      # 0.15% max bid-ask spread
MIN_PRICE          = 0.00001     # filter dust
CACHE_TTL_SECONDS  = 3600        # 1h cache; universe is stable intra-day

# ── Quality filters (2026-05-13 — fix knife-catching on memes/zombies) ────────
# Block symbols whose 24h price-change is catastrophic on either side. Captures
# meme-pump crashes and structural-decay bleeds. Mean-reversion does not work
# on tokens in directional collapse.
MAX_24H_DROP_PCT   = -0.20       # reject if 24h change worse than -20%
MAX_24H_RISE_PCT   = 0.50        # reject if 24h change above +50% (likely meme pump)

# ── Stablecoin / leveraged-token exclusion ────────────────────────────────────
_STABLES = {
    "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USDD", "FRAX", "USTC",
    "GUSD", "USDS", "PYUSD", "USDE", "EURT", "EURI", "PAX",
}
_LEVERAGED_PATTERNS = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")

# ── DENY-LIST (2026-05-13 — fix knife-catching) ───────────────────────────────
# Symbols that pass liquidity filters but are structurally inappropriate for
# mean-reversion strategies. Three categories:
#   A. Post-collapse zombies — high volume from speculation on dead chains
#   B. Memes — sentiment-driven, no fundamental BTC correlation
#   C. Wrapped / synthetic / illiquid-spot — execution-quality issues
# These tokens 'oversold' constantly because they're in structural decay, not
# noise. C3 mean-reversion fires forever and never reverts. Lock them out.
_DENY_LIST = {
    # Category A — zombies / post-collapse
    "LUNC", "USTC", "LUNA",        # Terra collapse, perpetual decay
    "FTT",                         # FTX defunct
    "SRM",                         # Serum frozen
    # Category B — memes / sentiment tokens
    "PEPE", "SHIB", "FLOKI", "BONK", "WIF", "MEME", "BABYDOGE",
    "DOGE",   # DOGE excluded from mean-reversion universe — too sentiment-driven
    "PENGU", "TURBO", "BRETT", "MOG", "POPCAT", "GOAT", "NEIRO",
    "PNUT", "ACT", "MEW", "TRUMP", "PEOPLE", "BOME",
    # Category C — wrapped/synthetic/illiquid-spot
    "WBTC", "WETH", "STETH", "WBETH", "WSTETH", "CBBTC", "TBTC",
    # Category D — known low-quality / privacy / delisting-risk
    "XMR", "ZEC", "DASH",          # privacy coins (delisting risk)
}

# Fallback if the API call fails entirely.
# Curated quality majors with strong BTC-beta correlation — safe for C3 mean-reversion.
FALLBACK_UNIVERSE = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
    "MATIC/USDT", "LTC/USDT", "ATOM/USDT", "UNI/USDT", "NEAR/USDT",
    "ARB/USDT", "OP/USDT", "APT/USDT", "SUI/USDT", "INJ/USDT",
    "BCH/USDT", "FIL/USDT", "TIA/USDT",
]


def _is_denied(base: str) -> bool:
    """Hard-block tokens in the deny-list (zombies, memes, wrapped synthetics)."""
    return base.upper() in _DENY_LIST

# In-process cache: (timestamp, universe_list)
_cache: dict[str, Any] = {"ts": 0.0, "tickers": None, "universe": None}


def _load_disk_cache() -> tuple[float, list[str]] | None:
    """Return (timestamp, universe) from disk cache, or None if unavailable/stale."""
    try:
        if not _DISK_CACHE_FILE.exists():
            return None
        data = json.loads(_DISK_CACHE_FILE.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0.0))
        universe = data.get("universe") or []
        if not universe:
            return None
        if (time.time() - ts) >= CACHE_TTL_SECONDS:
            return None
        return ts, universe
    except Exception as exc:
        log.debug("[universe] disk cache read failed: %s", exc)
        return None


def _save_disk_cache(ts: float, universe: list[str]) -> None:
    try:
        _DISK_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _DISK_CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"ts": ts, "universe": universe}, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_DISK_CACHE_FILE)
    except Exception as exc:
        log.debug("[universe] disk cache write failed: %s", exc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_stablecoin(base: str) -> bool:
    return base.upper() in _STABLES


def _is_leveraged_token(base: str) -> bool:
    up = base.upper()
    return any(up.endswith(p) for p in _LEVERAGED_PATTERNS)


def _spread_pct(ticker: dict) -> float | None:
    """Return (ask - bid) / mid as a fraction, or None if data unavailable."""
    bid = ticker.get("bid")
    ask = ticker.get("ask")
    if not bid or not ask or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid


def _passes_filters(symbol: str, ticker: dict) -> tuple[bool, str]:
    """
    Return (passes, reject_reason). reject_reason="" when passes is True.
    """
    if "/" not in symbol:
        return False, "no_slash"
    base, quote = symbol.split("/", 1)
    if quote != "USDT":
        return False, "quote_not_usdt"
    if _is_stablecoin(base):
        return False, "stablecoin_base"
    if _is_leveraged_token(base):
        return False, "leveraged_token"
    # 2026-05-13: hard-block known zombies / memes / wrapped synthetics.
    # See _DENY_LIST docstring for rationale.
    if _is_denied(base):
        return False, "denylist"

    # Volume floor (quote volume = volume × price)
    qv = ticker.get("quoteVolume")
    if qv is None:
        bv = ticker.get("baseVolume", 0.0) or 0.0
        last = ticker.get("last", 0.0) or 0.0
        qv = bv * last
    if not qv or qv < MIN_VOLUME_USD:
        return False, f"low_vol_{qv:.0f}"

    # Price floor
    last = ticker.get("last", 0.0) or 0.0
    if last < MIN_PRICE:
        return False, "dust_price"

    # Spread filter
    spread = _spread_pct(ticker)
    if spread is not None and spread > MAX_SPREAD_PCT:
        return False, f"wide_spread_{spread:.4f}"

    # 2026-05-13: 24h-change sanity filter. Catches catastrophic moves where
    # mean-reversion assumptions break (mid-collapse, mid-pump).
    # 'percentage' is decimal from CCXT (e.g. -0.25 = -25%).
    change_24h = ticker.get("percentage")
    if change_24h is not None:
        try:
            ch = float(change_24h)
            # CCXT sometimes returns percent (e.g. -25.0) instead of decimal.
            # Normalise: if abs(ch) > 5, assume percent and divide by 100.
            if abs(ch) > 5:
                ch = ch / 100.0
            if ch < MAX_24H_DROP_PCT:
                return False, f"crashing_{ch:.3f}"
            if ch > MAX_24H_RISE_PCT:
                return False, f"pumping_{ch:.3f}"
        except (TypeError, ValueError):
            pass

    return True, ""


# ── Public API ────────────────────────────────────────────────────────────────

def get_liquid_universe(
    top_n: int = 50,
    exchange=None,
    force_refresh: bool = False,
) -> list[str]:
    """
    Return the top-N most liquid Binance spot symbols passing all filters.

    Args:
        top_n: max symbols to return (sorted by 24h quote volume desc).
        exchange: optional ccxt.binance() instance. If None, builds one
                  via the same factory live_paper_runner uses.
        force_refresh: skip the in-process cache.

    Returns:
        list of symbol strings, e.g. ["BTC/USDT", "ETH/USDT", ...]
        Returns FALLBACK_UNIVERSE on hard failure.
    """
    now = time.time()
    if (not force_refresh
        and _cache["universe"] is not None
        and (now - _cache["ts"]) < CACHE_TTL_SECONDS):
        cached = _cache["universe"]
        log.debug("[universe] cache hit  n=%d  age=%.0fs", len(cached), now - _cache["ts"])
        return cached[:top_n]

    # 2026-05-13: try disk cache before hitting Binance (saves restart warmup).
    if not force_refresh:
        disk = _load_disk_cache()
        if disk is not None:
            disk_ts, disk_universe = disk
            _cache["ts"] = disk_ts
            _cache["universe"] = disk_universe
            log.info(
                "[universe] disk-cache hit  n=%d  age=%.0fs (skipped fetch_tickers)",
                len(disk_universe), now - disk_ts,
            )
            return disk_universe[:top_n]

    try:
        if exchange is None:
            try:
                from trading.live_paper_runner import _get_binance
                exchange = _get_binance()
            except Exception as exc:
                log.warning("[universe] could not get shared binance instance: %s", exc)
                import ccxt
                exchange = ccxt.binance({"enableRateLimit": True, "timeout": 30000})

        # Load all tickers in one call
        tickers = exchange.fetch_tickers()
        log.info("[universe] fetched %d raw tickers from Binance", len(tickers))

        candidates: list[tuple[str, float]] = []
        rejections: dict[str, int] = {}

        for sym, tk in tickers.items():
            ok, reason = _passes_filters(sym, tk)
            if not ok:
                rejections[reason.split("_")[0]] = rejections.get(reason.split("_")[0], 0) + 1
                continue
            qv = tk.get("quoteVolume") or (tk.get("baseVolume", 0) * tk.get("last", 0))
            candidates.append((sym, float(qv)))

        # Sort by 24h volume descending and take top N
        candidates.sort(key=lambda x: -x[1])
        universe = [s for s, _ in candidates[:top_n]]

        log.info(
            "[universe] kept=%d  rejected_by={%s}  top3=[%s]",
            len(universe),
            ", ".join(f"{k}:{v}" for k, v in sorted(rejections.items(), key=lambda x: -x[1])[:5]),
            ", ".join(universe[:3]),
        )

        _cache["ts"] = now
        _cache["tickers"] = tickers
        _cache["universe"] = universe
        _save_disk_cache(now, universe)
        return universe

    except Exception as exc:
        log.error("[universe] fetch failed (%s) — using fallback %d-symbol list",
                  exc, len(FALLBACK_UNIVERSE))
        return FALLBACK_UNIVERSE[:top_n]


def get_universe_metadata(symbol: str) -> dict | None:
    """
    Return cached ticker data for a symbol (24h volume, spread, last price, etc.).
    Useful for scoring + sizing decisions downstream.
    Returns None if symbol not in cache.
    """
    tickers = _cache.get("tickers")
    if tickers is None:
        return None
    tk = tickers.get(symbol)
    if not tk:
        return None
    return {
        "last":          tk.get("last"),
        "bid":           tk.get("bid"),
        "ask":           tk.get("ask"),
        "spread_pct":    _spread_pct(tk),
        "quote_volume":  tk.get("quoteVolume")
                          or (tk.get("baseVolume", 0) * tk.get("last", 0)),
        "change_24h":    tk.get("percentage"),
    }


def invalidate_cache() -> None:
    """Force-clear the cache (useful for tests or after a regime change)."""
    _cache["ts"] = 0.0
    _cache["tickers"] = None
    _cache["universe"] = None
