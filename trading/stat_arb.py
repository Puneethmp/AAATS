"""
AAATS Statistical Arbitrage — Pairs Trading Engine
====================================================
Market-neutral mean-reversion on cointegrated pairs.

Strategy logic (Engle-Granger simplified):
  1. Track the log price ratio (spread) of a pair.
  2. Compute rolling 20-bar z-score of the spread.
  3. Entry:  |z| > 2.0 → bet on mean reversion
  4. Exit:   |z| < 0.5 → spread has converged, close both legs

Pairs traded:
  Crypto  : BTC/USDT ↔ ETH/USDT  (most liquid, tightest bid-ask)
  NSE     : HDFCBANK  ↔ ICICIBANK  (cointegrated Indian bank pair)

State persists in data/stat_arb_state.json.

Usage (called from live_paper_runner.py):
    from trading.stat_arb import run_stat_arb_crypto, run_stat_arb_india
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_STATE_FILE = _ROOT / "data" / "stat_arb_state.json"
_DB_PATH = str(_ROOT / "data" / "paper_trades.db")

log = logging.getLogger("trading.stat_arb")

# ── Pair definitions ───────────────────────────────────────────────────────────

class Pair(NamedTuple):
    long_sym:  str    # symbol to BUY when spread is low
    short_sym: str    # symbol to SELL when spread is low
    market:    str    # "crypto" or "india"
    window:    int    # rolling z-score window (bars)
    entry_z:   float  # open position when |z| > this
    exit_z:    float  # close position when |z| < this
    alloc_pct: float  # fraction of market capital per leg

PAIRS = [
    Pair("BTC/USDT", "ETH/USDT", "crypto", 20, 2.0, 0.5, 0.04),
    Pair("HDFCBANK",  "ICICIBANK", "india", 20, 2.0, 0.5, 0.03),
]


# ── State management ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Spread computation ────────────────────────────────────────────────────────

def _compute_spread_zscore(
    prices_a: pd.Series, prices_b: pd.Series, window: int
) -> tuple[float, float]:
    """
    Compute log spread and its z-score over the last `window` bars.

    spread = log(price_a) - log(price_b)
    z      = (spread_now - mean(spread)) / std(spread)

    Returns (spread, z_score).
    """
    if len(prices_a) < window + 5 or len(prices_b) < window + 5:
        return 0.0, 0.0

    # Align on common index
    combined = pd.DataFrame({"a": prices_a, "b": prices_b}).dropna()
    if len(combined) < window + 2:
        return 0.0, 0.0

    log_a = np.log(combined["a"].clip(lower=1e-9))
    log_b = np.log(combined["b"].clip(lower=1e-9))
    spread = log_a - log_b

    rolling_mean = spread.rolling(window).mean()
    rolling_std  = spread.rolling(window).std().clip(lower=1e-9)

    spread_now = float(spread.iloc[-1])
    mean_now   = float(rolling_mean.iloc[-1])
    std_now    = float(rolling_std.iloc[-1])

    z = (spread_now - mean_now) / std_now
    return spread_now, z


# ── Execution helpers (mirrored from live_paper_runner but self-contained) ────

def _record_stat_arb_trade(
    market: str, symbol: str, action: str, shares: float,
    price: float, pnl: float = 0.0, note: str = "",
) -> None:
    """Write a stat-arb trade to the main paper_trades.db."""
    try:
        from execution.paper_trader import record_trade
        record_trade(
            db_path=_DB_PATH, market=market, symbol=symbol,
            action=action, shares=shares, price=price,
            signal="STAT_ARB", regime="PAIRS", risk_action="ALLOW",
            pnl=pnl if pnl != 0.0 else None, note=note,
        )
    except Exception as exc:
        log.warning(f"  stat_arb record_trade failed: {exc}")


def _send(msg: str, market: str) -> None:
    try:
        from observability.alerts import send_alert
        send_alert(msg, market=market)
    except Exception:
        pass


# ── Core pair runner ──────────────────────────────────────────────────────────

def _run_pair(
    pair: Pair,
    prices_a: pd.Series,
    prices_b: pd.Series,
    portfolio: dict,
    state: dict,
) -> dict:
    """
    Evaluate one pair and update positions.

    Position encoding in state:
        state[key] = {
            "side":        "LONG_A" | "SHORT_A",
            "shares_a":    float,
            "shares_b":    float,
            "entry_price_a": float,
            "entry_price_b": float,
            "entry_z":     float,
            "entry_time":  ISO string,
        }
    """
    key = f"{pair.long_sym}_{pair.short_sym}"
    mkt_port = portfolio[pair.market]
    capital  = mkt_port["capital"]

    spread, z = _compute_spread_zscore(prices_a, prices_b, pair.window)
    price_a   = float(prices_a.iloc[-1])
    price_b   = float(prices_b.iloc[-1])

    log.info(
        f"  [{pair.long_sym}/{pair.short_sym}] "
        f"spread={spread:.4f} z={z:+.3f} "
        f"prices=({price_a:.4f}, {price_b:.4f})"
    )

    position = state.get(key)
    alloc    = capital * pair.alloc_pct  # dollar allocation per leg

    # ── EXIT: position open and spread has converged ──────────────────────
    if position and abs(z) < pair.exit_z:
        side      = position["side"]
        shares_a  = position["shares_a"]
        shares_b  = position["shares_b"]
        entry_a   = position["entry_price_a"]
        entry_b   = position["entry_price_b"]
        entry_z   = position["entry_z"]

        if side == "LONG_A":
            # We were long A, short B
            pnl_a = (price_a - entry_a) * shares_a
            pnl_b = (entry_b - price_b) * shares_b   # short B profit
        else:
            # We were short A, long B
            pnl_a = (entry_a - price_a) * shares_a
            pnl_b = (price_b - entry_b) * shares_b

        total_pnl = pnl_a + pnl_b

        # Recover the original per-leg allocation charged at entry.
        # If state predates this fix, reconstruct from shares × entry_price.
        entry_alloc = position.get("entry_alloc")
        if entry_alloc is None:
            entry_alloc = position["shares_a"] * position["entry_price_a"]

        mkt_port["capital"]      += entry_alloc * 2 + total_pnl   # return alloc + credit PnL
        mkt_port["realized_pnl"] += total_pnl
        mkt_port["total_trades"] += 2

        if total_pnl >= 0:
            mkt_port["wins"] += 1
        else:
            mkt_port["losses"] += 1

        _record_stat_arb_trade(
            pair.market, pair.long_sym, "SELL", shares_a, price_a,
            pnl=pnl_a, note=f"stat_arb EXIT {side} | z={z:.3f} | entry_z={entry_z:.3f}",
        )
        _record_stat_arb_trade(
            pair.market, pair.short_sym, "BUY", shares_b, price_b,
            pnl=pnl_b, note=f"stat_arb EXIT {side} | z={z:.3f} | entry_z={entry_z:.3f}",
        )

        icon = "🟢" if total_pnl >= 0 else "🔴"
        log.info(
            f"  {icon} STAT_ARB EXIT {key} | side={side} "
            f"pnl={total_pnl:+.4f} | z={z:.3f}"
        )
        _send(
            f"{icon} STAT_ARB EXIT {key} | PnL={total_pnl:+.4f} | z_exit={z:.2f}",
            pair.market,
        )

        state.pop(key, None)

    # ── ENTRY: no position and spread is stretched ────────────────────────
    elif not position and abs(z) > pair.entry_z:
        # Check we have enough capital for both legs
        if alloc * 2 > capital:
            log.info(f"  ⚠️  Insufficient capital for stat_arb {key} — skip")
            return state

        shares_a = alloc / max(price_a, 1e-9)
        shares_b = alloc / max(price_b, 1e-9)

        if z > 0:
            # spread too wide → A expensive relative to B → LONG B, SHORT A
            side = "SHORT_A"
        else:
            # spread too narrow → A cheap relative to B → LONG A, SHORT B
            side = "LONG_A"

        state[key] = {
            "side":          side,
            "shares_a":      shares_a,
            "shares_b":      shares_b,
            "entry_price_a": price_a,
            "entry_price_b": price_b,
            "entry_z":       z,
            "entry_time":    datetime.now(timezone.utc).isoformat(),
            "entry_alloc":   alloc,
        }
        mkt_port["capital"]      -= alloc * 2
        mkt_port["total_trades"] += 2

        _record_stat_arb_trade(
            pair.market, pair.long_sym,
            "BUY" if side == "LONG_A" else "SELL",
            shares_a, price_a,
            note=f"stat_arb ENTRY {side} | z={z:.3f} | alloc={alloc:.2f}",
        )
        _record_stat_arb_trade(
            pair.market, pair.short_sym,
            "SELL" if side == "LONG_A" else "BUY",
            shares_b, price_b,
            note=f"stat_arb ENTRY {side} | z={z:.3f} | alloc={alloc:.2f}",
        )

        log.info(
            f"  📐 STAT_ARB ENTRY {key} | side={side} "
            f"z={z:.3f} | alloc={alloc:.2f}×2"
        )
        _send(
            f"📐 STAT_ARB ENTRY {key} | {side} | z={z:.2f} | alloc={alloc:.2f}×2",
            pair.market,
        )

    else:
        status = f"OPEN z={z:.3f}" if position else "no entry"
        log.debug(f"  [{key}] {status} — no action")

    return state


# ── Public runners ────────────────────────────────────────────────────────────

def run_stat_arb_crypto(
    portfolio: dict,
    fetch_hourly_fn,   # callable(symbol) → pd.DataFrame | None
) -> None:
    """
    Run crypto pairs stat-arb. Call once per cycle from run_crypto().

    Args:
        portfolio:      The live portfolio dict (mutated in-place).
        fetch_hourly_fn: Function that fetches hourly OHLCV DataFrame.
    """
    state = _load_state()
    crypto_pairs = [p for p in PAIRS if p.market == "crypto"]

    for pair in crypto_pairs:
        try:
            df_a = fetch_hourly_fn(pair.long_sym)
            df_b = fetch_hourly_fn(pair.short_sym)
            if df_a is None or df_b is None or len(df_a) < 25 or len(df_b) < 25:
                log.debug(f"  Insufficient data for {pair.long_sym}/{pair.short_sym}")
                continue

            prices_a = df_a.set_index("timestamp")["close"] if "timestamp" in df_a.columns else df_a["close"]
            prices_b = df_b.set_index("timestamp")["close"] if "timestamp" in df_b.columns else df_b["close"]

            state = _run_pair(pair, prices_a, prices_b, portfolio, state)
        except Exception as exc:
            log.error(f"  Stat-arb crypto {pair.long_sym}/{pair.short_sym}: {exc}", exc_info=True)

    _save_state(state)


def run_stat_arb_india(
    portfolio: dict,
    fetch_hourly_fn,   # callable(symbol, token, exchange) → pd.DataFrame | None
) -> None:
    """
    Run NSE pairs stat-arb. Call once per cycle from run_india().

    Args:
        portfolio:       The live portfolio dict (mutated in-place).
        fetch_hourly_fn: Function that fetches NSE hourly OHLCV DataFrame.
    """
    # Angel One token mapping for the NSE pairs
    _TOKEN_MAP = {
        "HDFCBANK":  ("1333", "NSE"),
        "ICICIBANK": ("4963", "NSE"),
    }

    state = _load_state()
    india_pairs = [p for p in PAIRS if p.market == "india"]

    for pair in india_pairs:
        try:
            token_a, exch_a = _TOKEN_MAP.get(pair.long_sym,  ("", "NSE"))
            token_b, exch_b = _TOKEN_MAP.get(pair.short_sym, ("", "NSE"))

            if not token_a or not token_b:
                log.warning(f"  Missing token for {pair.long_sym} or {pair.short_sym}")
                continue

            df_a = fetch_hourly_fn(pair.long_sym,  token_a, exch_a)
            df_b = fetch_hourly_fn(pair.short_sym, token_b, exch_b)

            if df_a is None or df_b is None or len(df_a) < 25 or len(df_b) < 25:
                log.debug(f"  Insufficient data for {pair.long_sym}/{pair.short_sym}")
                continue

            prices_a = df_a["close"] if "close" in df_a.columns else df_a.iloc[:, 4]
            prices_b = df_b["close"] if "close" in df_b.columns else df_b.iloc[:, 4]

            state = _run_pair(pair, prices_a, prices_b, portfolio, state)
        except Exception as exc:
            log.error(f"  Stat-arb India {pair.long_sym}/{pair.short_sym}: {exc}", exc_info=True)

    _save_state(state)


def get_open_stat_arb_positions() -> dict:
    """Return current open stat-arb positions for reporting."""
    return _load_state()


def get_stat_arb_summary(portfolio: dict) -> dict:
    """Return unrealized P&L and position count for the dashboard."""
    state = _load_state()
    summary = {
        "open_pairs":      len(state),
        "unrealized_pnl":  0.0,
        "positions":       [],
    }
    # We don't track current prices here — just report what's open
    for key, pos in state.items():
        summary["positions"].append({
            "pair":       key,
            "side":       pos.get("side"),
            "entry_z":    pos.get("entry_z"),
            "entry_time": pos.get("entry_time"),
        })
    return summary
