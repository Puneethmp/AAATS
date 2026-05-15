"""
markets/crypto/scanner.py  —  Per-strategy candidate ranker
===========================================================

PURPOSE
-------
Given the liquid universe (from universe.py), compute signal strength for
each strategy across every symbol and return a *ranked* candidate list.
Strategies then consume the top-K from their own list.

This is the heart of the scanner-first architecture: instead of running
strategies on a hand-picked watchlist, we *look across the whole market*
and let the data decide which symbols to trade.

USAGE
-----
    from markets.crypto.scanner import score_universe

    candidates = score_universe(
        universe=["BTC/USDT", "ETH/USDT", ...],   # from get_liquid_universe()
        fetch_hourly_fn=fetch_crypto_hourly,
        strategies=["c3", "c6"],
    )
    # → {
    #     "c3": [("OP/USDT", score=-2.4), ("ARB/USDT", -2.1), ...],
    #     "c6": [("LDO/USDT", score=0.91), ("MATIC/USDT", 0.87), ...],
    #   }

DESIGN
------
- One pass through the universe per cycle. Indicators computed once per
  symbol; multiple strategies share the OHLCV fetch.
- All scores returned are ASCENDING-ranked: more negative / lower = better
  candidate. Each strategy's `score()` defines its own polarity.
- Hard-rejected symbols (insufficient data, indicator NaN, etc.) are
  silently dropped. The result is "candidates ready for entry."

OUTPUT
------
Dict mapping strategy_name -> list of (symbol, score) tuples sorted
strongest-first. Caller (portfolio_allocator) applies caps and selects
the final tradeable set.
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ── Strategy scoring functions ────────────────────────────────────────────────
# Convention: lower score = stronger BUY candidate.
# Returns +inf to signal "do not enter" (e.g., conditions not met).

def _score_c3_mean_reversion(
    alt_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    lookback: int = 60,
) -> float:
    """
    C3 score = z-score of log(ALT/BTC) over `lookback` bars.
    Negative z = alt is cheap vs BTC = stronger BUY candidate.
    Returns +inf if data insufficient or invariant.
    """
    try:
        n = min(len(alt_df), len(btc_df))
        if n < lookback + 5:
            return float("inf")
        alt_c = alt_df["close"].values[-n:]
        btc_c = btc_df["close"].values[-n:]
        ratio = np.log(alt_c / btc_c)
        window = ratio[-lookback:]
        mean   = window.mean()
        std    = window.std(ddof=1)
        if std < 1e-9:
            return float("inf")
        return float((ratio[-1] - mean) / std)
    except Exception as exc:
        log.debug("[scanner.c3] score error: %s", exc)
        return float("inf")


def _score_c6_bollinger(
    df: pd.DataFrame,
    period: int = 20,
    n_std: float = 2.0,
    rsi_period: int = 14,
) -> tuple[float, float, float]:
    """
    C6 score = composite oversold strength = (PCT_B_ENTRY - %B) + (RSI_ENTRY - RSI)/100.
    Higher score = more oversold = stronger BUY candidate.
    For RANKING ASCENDING, we return -composite (so lower = better, like c3).
    Returns (score, pct_b, rsi).
    """
    try:
        if len(df) < period + 5:
            return float("inf"), 0.5, 50.0
        closes = df["close"]
        rolling = closes.rolling(period)
        mid = rolling.mean().iloc[-1]
        std = rolling.std(ddof=0).iloc[-1]
        if pd.isna(mid) or pd.isna(std) or std < 1e-9:
            return float("inf"), 0.5, 50.0
        upper = mid + n_std * std
        lower = mid - n_std * std
        pct_b = (closes.iloc[-1] - lower) / (upper - lower)

        # RSI
        delta = closes.diff().dropna()
        if len(delta) < rsi_period:
            rsi = 50.0
        else:
            gain = delta.where(delta > 0, 0.0).rolling(rsi_period).mean().iloc[-1]
            loss = (-delta.where(delta < 0, 0.0)).rolling(rsi_period).mean().iloc[-1]
            if loss == 0:
                rsi = 100.0
            else:
                rs = gain / loss
                rsi = 100 - 100 / (1 + rs)

        # Composite: more oversold = lower score
        # We want symbols with %B < 0.15 AND RSI < 32. Score them by how
        # far they are below those thresholds. The candidate with the
        # lowest score is the most oversold.
        pct_b_excess = float(pct_b - 0.15)        # negative = below entry threshold
        rsi_excess   = (float(rsi) - 32.0) / 100  # negative = below entry threshold
        composite    = pct_b_excess + rsi_excess  # sum of "how far below thresholds"
        return composite, float(pct_b), float(rsi)
    except Exception as exc:
        log.debug("[scanner.c6] score error: %s", exc)
        return float("inf"), 0.5, 50.0


def _passes_c6_hard_gates(pct_b: float, rsi: float) -> bool:
    """C6 hard gates same as in bollinger_range.py — must hold before listing as candidate."""
    return pct_b < 0.15 and rsi < 32.0


def _passes_c3_hard_gate(z: float) -> bool:
    """C3 hard gate — z must be below entry threshold."""
    return z < -1.6


# ── Public scanner ────────────────────────────────────────────────────────────

def score_universe(
    universe: list[str],
    fetch_hourly_fn: Callable[[str], pd.DataFrame | None],
    strategies: list[str] = ("c3", "c6"),
    btc_df: pd.DataFrame | None = None,
) -> dict[str, list[tuple[str, float]]]:
    """
    Score every symbol in `universe` against each strategy. Return ranked candidates.

    Args:
        universe:         output of get_liquid_universe().
        fetch_hourly_fn:  callable(symbol) -> pd.DataFrame | None
        strategies:       which strategies to score. Default: c3 + c6.
        btc_df:           pre-fetched BTC 1H OHLCV (avoids re-fetch). If None,
                          we fetch it here.

    Returns:
        {strategy_name: [(symbol, score), ...]} sorted by score ASCENDING.
        Only symbols PASSING the strategy's hard gates are included.
    """
    result: dict[str, list[tuple[str, float]]] = {s: [] for s in strategies}

    # ── Pre-fetch BTC for C3 (its score requires alt/BTC ratio) ──────────────
    if "c3" in strategies and btc_df is None:
        try:
            btc_df = fetch_hourly_fn("BTC/USDT")
            if btc_df is None or len(btc_df) < 70:
                log.warning("[scanner] BTC data unavailable — disabling c3 this cycle")
                strategies = [s for s in strategies if s != "c3"]
        except Exception as exc:
            log.warning("[scanner] BTC fetch failed: %s — disabling c3", exc)
            strategies = [s for s in strategies if s != "c3"]

    # ── One pass through universe ────────────────────────────────────────────
    fetched = 0
    skipped = 0

    for sym in universe:
        try:
            df = fetch_hourly_fn(sym)
            if df is None or len(df) < 70:
                skipped += 1
                continue
            fetched += 1

            # Score for each strategy
            if "c3" in strategies and sym != "BTC/USDT":
                z = _score_c3_mean_reversion(df, btc_df)
                if _passes_c3_hard_gate(z):
                    result["c3"].append((sym, z))

            if "c6" in strategies:
                score, pct_b, rsi = _score_c6_bollinger(df)
                if _passes_c6_hard_gates(pct_b, rsi):
                    result["c6"].append((sym, score))

        except Exception as exc:
            log.debug("[scanner] %s error: %s", sym, exc)
            skipped += 1

    # ── Sort ASCENDING (lowest score = strongest candidate) ──────────────────
    for s in result:
        result[s].sort(key=lambda x: x[1])

    log.info(
        "[scanner] universe=%d fetched=%d skipped=%d  candidates: %s",
        len(universe), fetched, skipped,
        ", ".join(f"{s}={len(c)}" for s, c in result.items()),
    )

    # Log top-3 candidates per strategy for visibility
    for strat, cands in result.items():
        if cands:
            top3 = ", ".join(f"{sym}({sc:+.3f})" for sym, sc in cands[:3])
            log.info("[scanner] %s top3: %s", strat, top3)

    return result
