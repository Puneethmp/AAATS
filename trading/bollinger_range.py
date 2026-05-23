"""
trading/bollinger_range.py  —  C6 Bollinger Range Trader (NEW, 2026-05-12)
==========================================================================

PURPOSE
-------
Fill the RANGE_BOUND regime gap. C1 (stat-arb), C2 (momentum breakout) and
the ensemble all under-fire in sideways markets. This module is a direct-
execution mean-reversion trader for BTC/ETH/SOL — the most liquid spot
pairs available on Binance — that fires precisely when those other
strategies sit out.

WHY THIS EXISTS
---------------
Phase 1 status (2026-05-12):
  • Capital: $120
  • Regime: RANGE_BOUND for multiple sessions
  • Existing strategies' fire rates in current tape: ~0/day
  • Activity needed to validate engineering + earn the $1.5k injection

C3 mean reversion (altcoin_reversion.py) handles alts vs BTC.
This module handles BTC/ETH/SOL on absolute BBand mechanics — different
signal, complementary trades. Z-score relative to BTC ≠ extension of
absolute price from its own moving average.

STRATEGY
--------
Entry  (ALL must hold):
  • regime == "RANGE_BOUND"                      (regime filter)
  • %B  < 0.15                                   (price near lower band)
  • RSI(14) < 32                                 (oversold)
  • Last 4 bars avg volume > 0.6 × 20-bar avg    (not dead-tape)
  • No existing open position in this symbol from any strategy

Exits (whichever fires first):
  • %B  >= 0.50                                  (midline reversion = target)
  • PnL >= +1.5%                                 (alt take-profit)
  • PnL <= -1.0%                                 (hard stop)
  • Age >= 12 hours                              (time stop — release capital)
  • Regime flip to TREND_*                       (mean-reversion thesis broken)

CAPITAL
-------
  • CAPITAL_PCT = 0.06  (6% per trade ≈ $7.20 on $120)
  • MIN_TRADE_USD = 5.0  (Binance practical minimum)
  • Max 2 concurrent positions across the universe — avoid overloading.

EXPECTED BEHAVIOR ($120, 48h)
-----------------------------
  • 2–6 entries over 48h in RANGE_BOUND regime
  • Win rate target: 55–60% (oversold bounces in range)
  • Avg winner: +1.3%  |  Avg loser: -0.8%  →  EV ~+0.4% per trade
  • Per-trade absolute: $7.20 × 0.4% = $0.029  ≈  $0.06–0.20 / 48h gross
  • Real value: SIGNAL DENSITY for engineering validation, not PnL

WIRING
------
Called from `trading/live_paper_runner.run_crypto()` after C3 block:
    from trading.bollinger_range import run_bollinger_range_crypto
    run_bollinger_range_crypto(portfolio["crypto"], fetch_crypto_hourly, positions)

State persisted to: data/bollinger_range_state.json
Trades recorded to: data/paper_trades.db   strategy="C6_bollinger_range"
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parents[1]

SYMBOLS              = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
CAPITAL_PCT          = 0.06       # 6% of crypto portfolio per trade
MIN_TRADE_USD        = 5.0        # below this = skip (fees eat edge)
MAX_CONCURRENT       = 2          # max open C6 positions across universe

BB_PERIOD            = 20
BB_STD               = 2.0
PCT_B_ENTRY          = 0.15       # entry: %B below this (very near lower band)
PCT_B_TARGET         = 0.50       # exit target: %B reverted to midline
RSI_ENTRY            = 32         # oversold entry confirmation
RSI_PERIOD           = 14

TAKE_PROFIT_PCT      = 0.015      # +1.5% absolute take-profit
HARD_STOP_PCT        = -0.010     # -1.0% hard stop
TIME_STOP_HOURS      = 12         # release capital after 12h

VOL_RATIO_FLOOR      = 0.60       # last-4-bar vol / 20-bar vol must exceed this

STATE_FILE           = _ROOT / "data" / "bollinger_range_state.json"
DB_PATH              = str(_ROOT / "data" / "paper_trades.db")

# Unified positions ledger wiring (Q1-Q4=A, ledger commit 3/3 2026-05-21).
# Flag is read ONCE at module import per Q4=A; flips require container restart.
from foundation import state_bridge as _state_bridge

STRATEGY_ID = "C6_bollinger_range"
MARKET = "crypto"
_USE_UNIFIED_LEDGER = _state_bridge.is_unified_ledger_enabled()


# ── State helpers ─────────────────────────────────────────────────────────────
def _load_state() -> dict[str, Any]:
    if _USE_UNIFIED_LEDGER:
        return _state_bridge.load_state(STRATEGY_ID, MARKET, STATE_FILE,
                                        use_unified=True)
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("[c6] state file unreadable (%s) — starting fresh", exc)
    return {}


def _save_state(state: dict[str, Any]) -> None:
    if _USE_UNIFIED_LEDGER:
        _state_bridge.save_state(STRATEGY_ID, MARKET, state, STATE_FILE,
                                 use_unified=True)
        return
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _age_hours(entry_ts: str) -> float:
    try:
        ts = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except Exception:
        return 0.0


# ── Indicator helpers ─────────────────────────────────────────────────────────
def _rsi(series: pd.Series, period: int = RSI_PERIOD) -> float:
    delta = series.diff().dropna()
    if len(delta) < period:
        return 50.0
    gain = delta.where(delta > 0, 0.0).rolling(period).mean().iloc[-1]
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean().iloc[-1]
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100 - 100 / (1 + rs))


def _bollinger_pct_b(closes: pd.Series, period: int = BB_PERIOD,
                     n_std: float = BB_STD) -> tuple[float, float, float]:
    """
    Returns (pct_b, mid, std).
      pct_b = (close - lower) / (upper - lower)
      pct_b 0.0 = at lower band, 0.5 = midline, 1.0 = upper band, <0 = below band
    """
    rolling = closes.rolling(period)
    mid     = rolling.mean().iloc[-1]
    std     = rolling.std(ddof=0).iloc[-1]
    if pd.isna(mid) or pd.isna(std) or std < 1e-9:
        return 0.5, float(mid or closes.iloc[-1]), 0.0
    upper   = mid + n_std * std
    lower   = mid - n_std * std
    pct_b   = (closes.iloc[-1] - lower) / (upper - lower)
    return float(pct_b), float(mid), float(std)


def _volume_healthy(df: pd.DataFrame) -> bool:
    """Last-4-bar average volume must be >= VOL_RATIO_FLOOR × 20-bar average."""
    try:
        vols    = df["volume"].astype(float)
        last_4  = vols.iloc[-4:].mean()
        avg_20  = vols.iloc[-20:].mean()
        if avg_20 <= 0:
            return False
        return (last_4 / avg_20) >= VOL_RATIO_FLOOR
    except Exception:
        return True   # if volume data unavailable, do not block — log only


# ── DB record helper ──────────────────────────────────────────────────────────
def _record(symbol: str, action: str, price: float, size_usd: float,
            pnl: float = 0.0, entry_time: str | None = None,
            exit_time: str | None = None, pnl_pct: float | None = None,
            pct_b: float = 0.0, rsi: float = 0.0, exit_reason: str = "",
            shares: float | None = None) -> None:
    try:
        from execution.paper_trader import record_trade
        # SELL must record the same shares that the BUY row stored, otherwise
        # paper_trades SUM(BUY) - SUM(SELL) leaves residual dust per closed
        # position. Caller passes entry-derived shares for SELL.
        recorded_shares = (
            float(shares)
            if shares is not None
            else round(size_usd / max(price, 1e-9), 8)
        )
        record_trade(
            db_path=DB_PATH, market="crypto", symbol=symbol,
            action=action,
            shares=recorded_shares,
            price=price, signal="C6_BOLLINGER_RANGE",
            regime="RANGE_BOUND", risk_action="ALLOW",
            pnl=pnl,
            note=f"C6 {action} %B={pct_b:.3f} RSI={rsi:.1f}",
            strategy="C6_bollinger_range",
            entry_time=entry_time, exit_time=exit_time,
            pnl_pct=pnl_pct, size_usd=round(size_usd, 4),
            notes={
                "pct_b": round(pct_b, 4),
                "rsi": round(rsi, 2),
                "exit_reason": exit_reason,
                "confidence": 0.65,
            },
        )
    except Exception as exc:
        log.warning("[c6] record_trade failed: %s", exc)


# ── Public runner ──────────────────────────────────────────────────────────────
def run_bollinger_range_crypto(
    portfolio: dict,
    fetch_hourly_fn: Callable[[str], pd.DataFrame | None],
    open_positions: dict | None = None,
    symbols: list[str] | None = None,
    full_positions: dict | None = None,
    full_portfolio: dict | None = None,
) -> None:
    """
    One C6 cycle. Mutates portfolio["capital"] in-place.

    Args:
      portfolio:        crypto sub-portfolio dict {"capital": float, ...}
      fetch_hourly_fn:  function(symbol) -> 1H OHLCV DataFrame
      open_positions:   {symbol: pos_dict}, used to skip if another strategy
                        already holds this symbol. Pass positions["crypto"]
                        from live_paper_runner. None = don't enforce.
      symbols:          Optional injected list (e.g. from scanner+allocator).
                        When provided, overrides hardcoded SYMBOLS. None =
                        use defaults (backward compat).
      full_positions:   Full positions dict {"crypto": {...}, "india": {...}}.
                        Required for kill-switch gate (B' helper). When None
                        (test/back-compat callers), the gate is bypassed.
      full_portfolio:   Full portfolio dict, same role as full_positions.
    """
    _gate_check = None
    _exit_gate_check = None
    if full_positions is not None and full_portfolio is not None:
        try:
            from trading.live_paper_runner import (
                apply_kill_switch_gate as _gate_check,
                apply_kill_switch_exit_gate as _exit_gate_check,
            )
        except Exception as exc:
            log.warning("[c6] kill-switch helper unavailable (%s) — proceeding ungated", exc)
            _gate_check = None
            _exit_gate_check = None
    state   = _load_state()
    changed = False
    capital = portfolio.get("capital", 0.0)

    # Pull current regime from runner cache
    try:
        from trading.live_paper_runner import detect_regime
    except Exception:
        detect_regime = None

    open_now = sum(1 for _ in state.values())

    universe = symbols if symbols is not None else SYMBOLS

    # Same orphan-by-design fix as C3 (commit f137cb3). When the runner's
    # scanner-derived c6_picks excludes held symbols (allocator.py:167), the
    # strategy would otherwise never re-evaluate held positions outside the
    # per-cycle universe — orphaning all exit conditions including the 12h
    # time stop. Entry branch is gated by `pos is None`, so held_outside
    # symbols only exercise the manage-open branch.
    held_outside = sorted(set(state) - set(universe))
    if held_outside:
        log.info(
            "[c6] also evaluating %d held position(s) outside picks: %s",
            len(held_outside), held_outside,
        )
    to_evaluate = list(universe) + held_outside

    for sym in to_evaluate:
        try:
            df = fetch_hourly_fn(sym)
            if df is None or len(df) < BB_PERIOD + 10:
                log.debug("[c6] %s: insufficient data", sym)
                continue

            price = float(df["close"].iloc[-1])
            pct_b, mid, std = _bollinger_pct_b(df["close"])
            rsi = _rsi(df["close"])

            # Regime check (entry-side only; exit checks below)
            regime = "UNKNOWN"
            if detect_regime is not None:
                try:
                    regime, _ = detect_regime(sym, df)
                except Exception:
                    regime = "UNKNOWN"

            log.info("[c6] %s  price=%.4f  %%B=%.3f  RSI=%.1f  regime=%s",
                     sym, price, pct_b, rsi, regime)

            pos = state.get(sym)

            # ── Manage open position ──────────────────────────────────────────
            if pos is not None:
                entry_price = pos["entry_price"]
                size_usd    = pos["size_usd"]
                age_h       = _age_hours(pos["entry_ts"])
                pnl         = size_usd * (price - entry_price) / entry_price
                pnl_pct     = (price - entry_price) / entry_price

                exit_reason = ""
                if pct_b >= PCT_B_TARGET:
                    exit_reason = f"pct_b_target({pct_b:.3f}>={PCT_B_TARGET})"
                elif pnl_pct >= TAKE_PROFIT_PCT:
                    exit_reason = f"take_profit({pnl_pct*100:.2f}%)"
                elif pnl_pct <= HARD_STOP_PCT:
                    exit_reason = f"hard_stop({pnl_pct*100:.2f}%)"
                elif age_h >= TIME_STOP_HOURS:
                    exit_reason = f"time_stop({age_h:.1f}h)"
                elif regime in ("BULL_TREND", "BEAR_TREND") and age_h > 1.0:
                    exit_reason = f"regime_flip({regime})"

                if exit_reason:
                    # EXIT gate (session 8, 2026-05-23): only catastrophic
                    # HALT_ALL blocks. Per-market HALT_MARKET (drawdown <=
                    # -15%) and operator halt allow the SELL through —
                    # those are 'block new entries' channels, not 'block
                    # all activity' channels. See
                    # docs/known_issues/2026-05-23_kill_trigger_investigation.md.
                    if _exit_gate_check is not None:
                        _allowed, _kill_reason = _exit_gate_check(
                            "crypto", sym, price,
                            full_positions, full_portfolio,
                        )
                        if not _allowed:
                            log.info(
                                "[c6] %s: SKIP SELL — HALT_ALL active (%s)",
                                sym, _kill_reason,
                            )
                            continue

                    exit_ts  = datetime.now(timezone.utc).isoformat()
                    capital += size_usd + pnl
                    portfolio["capital"] = capital

                    _record(symbol=sym, action="SELL", price=price,
                            size_usd=size_usd, pnl=pnl,
                            entry_time=pos["entry_ts"], exit_time=exit_ts,
                            pnl_pct=round(pnl_pct * 100, 4),
                            pct_b=pct_b, rsi=rsi, exit_reason=exit_reason,
                            shares=round(
                                pos["size_usd"] / max(pos["entry_price"], 1e-9),
                                8,
                            ))
                    log.info(
                        "[c6] EXIT  %s  reason=%s  pnl=$%.4f (%+.2f%%)  cap=$%.2f",
                        sym, exit_reason, pnl, pnl_pct * 100, capital,
                    )
                    del state[sym]
                    open_now -= 1
                    changed = True
                else:
                    log.info("[c6] HOLD  %s  pnl=%+.2f%%  age=%.1fh  %%B=%.3f",
                             sym, pnl_pct * 100, age_h, pct_b)

            # ── Check entry ───────────────────────────────────────────────────
            else:
                # Cap concurrent positions
                if open_now >= MAX_CONCURRENT:
                    log.debug("[c6] %s: max concurrent (%d) reached — skip entry",
                              sym, MAX_CONCURRENT)
                    continue

                # Don't double up with other strategies on same symbol
                if open_positions is not None:
                    other = open_positions.get(sym)
                    if other and abs(float(other.get("shares", 0.0))) > 1e-9:
                        log.debug("[c6] %s: another strategy holds position — skip",
                                  sym)
                        continue

                # Hard gates
                if regime != "RANGE_BOUND":
                    continue
                if pct_b >= PCT_B_ENTRY:
                    continue
                if rsi >= RSI_ENTRY:
                    continue
                if not _volume_healthy(df):
                    log.info("[c6] %s: volume below floor — skip", sym)
                    continue

                trade_usd = capital * CAPITAL_PCT
                if trade_usd < MIN_TRADE_USD:
                    log.info("[c6] %s: trade size $%.2f < min $%.2f — skip",
                             sym, trade_usd, MIN_TRADE_USD)
                    continue

                # Kill-switch gate (B') — block BUY emission BEFORE any state
                # mutation, DB write, or capital adjustment.
                if _gate_check is not None:
                    _allowed, _kill_reason = _gate_check(
                        "crypto", sym, price,
                        full_positions, full_portfolio,
                    )
                    if not _allowed:
                        log.info(
                            "[c6] %s: SKIP BUY — kill switch active (%s)",
                            sym, _kill_reason,
                        )
                        continue

                entry_ts = datetime.now(timezone.utc).isoformat()
                capital -= trade_usd
                portfolio["capital"] = capital

                state[sym] = {
                    "entry_price": price,
                    "entry_ts":    entry_ts,
                    "size_usd":    trade_usd,
                    "entry_pct_b": pct_b,
                    "entry_rsi":   rsi,
                }
                open_now += 1
                changed   = True

                _record(symbol=sym, action="BUY", price=price,
                        size_usd=trade_usd, entry_time=entry_ts,
                        pct_b=pct_b, rsi=rsi, exit_reason="")
                log.info(
                    "[c6] ENTRY %s  %%B=%.3f  RSI=%.1f  size=$%.2f  cap=$%.2f",
                    sym, pct_b, rsi, trade_usd, capital,
                )

        except Exception as exc:
            log.error("[c6] %s cycle error: %s", sym, exc, exc_info=True)

    if changed:
        _save_state(state)
