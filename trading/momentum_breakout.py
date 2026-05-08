"""
trading/momentum_breakout.py  —  C2: 4H Momentum Breakout (BTC + ETH only)

Strategy spec:
  Universe:   BTC/USDT, ETH/USDT only (large-cap, sufficient liquidity)
  Timeframe:  4H candles (resampled from 1H feed)
  Entry:      close > 20-bar rolling high  AND  RSI(14) > 52  AND  vol > 1.4× 20-bar avg
  Regime:     4H EMA12 > EMA26 (BULL proxy) — skip entries in BEAR/RANGE
  F&G filter: Fear & Greed index must be > 40 (not extreme fear)
  Capital:    6% of crypto portfolio per position ($6.60 at $110 base)
  Target:     +2.0% from entry
  Time stop:  if not +0.8% profit after 8H → exit (stagnant trade)
  Hard stop:  -1.2% from entry (asymmetric: risk 1.2 to make 2.0 = 1.67 R:R)
  Stagnation: if |price change from entry| < 0.3% after a full 4H bar → exit

  Max concurrent: 1 position per symbol (2 max total across BTC+ETH)

Wire-in: live_paper_runner.py calls run_momentum_breakout_crypto() at end of cycle.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from execution.paper_trader import record_trade

log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

SYMBOLS           = ["BTC/USDT", "ETH/USDT"]
CAPITAL_PCT       = 0.06        # 6% of crypto portfolio per trade
BREAKOUT_BARS     = 20          # rolling high lookback (4H bars)
RSI_ENTRY_MIN     = 52          # RSI must be above this on 4H
VOL_MULT          = 1.4         # volume must be > 1.4× 20-bar avg
TARGET_PCT        = 0.020       # +2.0% profit target
STOP_PCT          = 0.012       # -1.2% hard stop
TIME_STOP_HOURS   = 8           # exit if not +0.8% profit after 8H
TIME_STOP_MIN_PCT = 0.008       # minimum profit to NOT trigger time stop
STAGNATION_PCT    = 0.003       # < 0.3% move from entry after 1 full 4H bar → exit
FG_MIN            = 40          # Fear & Greed minimum (skip entries in extreme fear)
DB_PATH           = "data/paper_trades.db"
STATE_FILE        = Path("data/momentum_state.json")
FG_CACHE          = Path("data/fear_greed_cache.json")

# ─── State I/O ────────────────────────────────────────────────────────────────

def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        raw = STATE_FILE.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"[c2] state unreadable ({exc}), starting fresh")
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Resample 1H OHLCV dataframe to 4H bars."""
    df = df_1h.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, utc=True)
        except Exception:
            return pd.DataFrame()
    df = df.sort_index()
    ohlcv = df[["open", "high", "low", "close", "volume"]].resample("4h").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    return ohlcv


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add RSI(14), EMA12, EMA26, rolling_high_20, vol_avg_20 to 4H df."""
    out = df.copy()
    close = out["close"]
    volume = out["volume"]

    # RSI(14) — Wilder's method approximated by ewm
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs    = gain / loss.replace(0, float("nan"))
    out["rsi_14"] = 100 - (100 / (1 + rs))

    # EMA regime proxy
    out["ema_12"] = close.ewm(span=12, adjust=False).mean()
    out["ema_26"] = close.ewm(span=26, adjust=False).mean()

    # Breakout: rolling high of last N bars (shift(1) = exclude current bar)
    out["rolling_high_20"] = out["high"].rolling(BREAKOUT_BARS).max().shift(1)

    # Volume filter
    out["vol_avg_20"] = volume.rolling(BREAKOUT_BARS).mean()

    return out.dropna(subset=["rsi_14", "rolling_high_20", "vol_avg_20"])


def _fear_greed() -> int:
    """Read cached F&G index (0–100). Returns 50 if unavailable."""
    try:
        if FG_CACHE.exists():
            data = json.loads(FG_CACHE.read_text(encoding="utf-8"))
            return int(data.get("value", 50))
    except Exception:
        pass
    return 50


def _age_hours(entry_ts: str) -> float:
    try:
        entry_dt = datetime.fromisoformat(entry_ts)
        return (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600.0
    except Exception:
        return 0.0


# ─── Entry / exit logic ───────────────────────────────────────────────────────

def _compute_confidence(df4h: pd.DataFrame) -> float:
    """
    Return a 0.0–1.0 confidence score for the last 4H bar.
    Composite of 4 factors: breakout strength, RSI momentum, volume surge, sentiment.
    Each sub-score is clipped to [0, 1] then averaged.
    """
    if len(df4h) < 2:
        return 0.0
    last = df4h.iloc[-1]
    close   = float(last["close"])
    rsi     = float(last["rsi_14"])
    vol     = float(last["volume"])
    vol_avg = float(last["vol_avg_20"])
    rh20    = float(last["rolling_high_20"])
    fg      = _fear_greed()

    breakout_score = min((close - rh20) / (rh20 * 0.05), 1.0) if rh20 > 0 else 0.0
    rsi_score      = min((rsi - RSI_ENTRY_MIN) / (100 - RSI_ENTRY_MIN), 1.0)
    vol_score      = min((vol / vol_avg - VOL_MULT) / (5.0 - VOL_MULT), 1.0) if vol_avg > 0 else 0.0
    fg_score       = min((fg - FG_MIN) / (100 - FG_MIN), 1.0)

    return round(max(0.0, (breakout_score + rsi_score + vol_score + fg_score) / 4.0), 4)


def _entry_conditions(df4h: pd.DataFrame) -> bool:
    """Check all entry conditions on the last completed 4H bar."""
    if len(df4h) < BREAKOUT_BARS + 2:
        return False
    last = df4h.iloc[-1]

    close    = float(last["close"])
    rsi      = float(last["rsi_14"])
    vol      = float(last["volume"])
    vol_avg  = float(last["vol_avg_20"])
    rh20     = float(last["rolling_high_20"])
    ema12    = float(last["ema_12"])
    ema26    = float(last["ema_26"])

    breakout = close > rh20
    rsi_ok   = rsi > RSI_ENTRY_MIN
    vol_ok   = vol_avg > 0 and (vol / vol_avg) >= VOL_MULT
    bull_reg = ema12 > ema26
    fg_ok    = _fear_greed() >= FG_MIN

    log.debug(
        f"  [c2] entry check: breakout={breakout}(close={close:.2f}>rh={rh20:.2f}) "
        f"rsi={rsi:.1f} vol_x={vol/vol_avg:.2f} bull={bull_reg} fg={_fear_greed()}"
    )
    return breakout and rsi_ok and vol_ok and bull_reg and fg_ok


def _check_exits(sym: str, pos: dict[str, Any], current_price: float,
                 df4h: pd.DataFrame) -> tuple[bool, str]:
    """
    Returns (should_exit, reason).
    Checks: target, hard stop, time stop, stagnation.
    """
    entry  = pos["entry_price"]
    pct    = (current_price - entry) / entry

    # 1. Profit target
    if pct >= TARGET_PCT:
        return True, f"target({pct:.2%})"

    # 2. Hard stop
    if pct <= -STOP_PCT:
        return True, f"hard_stop({pct:.2%})"

    # 3. Time stop: 8H elapsed and not yet +0.8%
    age = _age_hours(pos["entry_ts"])
    if age >= TIME_STOP_HOURS and pct < TIME_STOP_MIN_PCT:
        return True, f"time_stop(age={age:.1f}h,pct={pct:.2%})"

    # 4. Stagnation: one full 4H bar closed and price barely moved
    if age >= 4.0:
        last_4h_close = pos.get("last_4h_close", entry)
        move_since_4h = abs(current_price - last_4h_close) / last_4h_close
        if move_since_4h < STAGNATION_PCT:
            return True, f"stagnation(move={move_since_4h:.3%})"

    return False, ""


# ─── Public runner ─────────────────────────────────────────────────────────────

def run_momentum_breakout_crypto(portfolio: dict, fetch_hourly_fn) -> None:
    """
    Main entry point — called once per cycle from live_paper_runner.

    Args:
        portfolio:       Full portfolio dict (uses portfolio["crypto"]["capital"])
        fetch_hourly_fn: Callable(symbol) → pd.DataFrame | None  (1H OHLCV)
    """
    state   = _load_state()
    changed = False
    capital = portfolio.get("capital", 0.0)   # crypto sub-dict already passed in

    for sym in SYMBOLS:
        try:
            df_1h = fetch_hourly_fn(sym)
            if df_1h is None or len(df_1h) < 50:
                log.debug(f"[c2] {sym}: insufficient 1H data")
                continue

            df4h = _resample_4h(df_1h)
            if len(df4h) < BREAKOUT_BARS + 2:
                log.debug(f"[c2] {sym}: insufficient 4H bars ({len(df4h)})")
                continue

            df4h = _add_indicators(df4h)
            current_price = float(df4h["close"].iloc[-1])
            pos = state.get(sym)

            # ── MANAGE OPEN POSITION ──────────────────────────────────────────
            if pos is not None:
                # Update last_4h_close each cycle (end of 4H bar tracker)
                last_bar_close = float(df4h["close"].iloc[-1])
                if last_bar_close != pos.get("last_4h_close"):
                    pos["last_4h_close"] = last_bar_close
                    changed = True

                exit_now, reason = _check_exits(sym, pos, current_price, df4h)
                if exit_now:
                    entry   = pos["entry_price"]
                    size    = pos["size_usd"]
                    pnl     = size * (current_price - entry) / entry
                    capital += size + pnl
                    portfolio["capital"] = capital

                    _exit_ts = datetime.now(timezone.utc).isoformat()
                    conf = _compute_confidence(df4h)
                    record_trade(
                        db_path=DB_PATH, market="crypto", symbol=sym,
                        action="SELL", shares=size / entry,
                        price=current_price, signal="C2_EXIT",
                        regime="BULL", pnl=pnl,
                        note=f"C2 exit: {reason}",
                        strategy="C2_momentum",
                        entry_time=pos.get("entry_ts"),
                        exit_time=_exit_ts,
                        pnl_pct=round(pnl / size * 100, 4) if size else None,
                        size_usd=round(size, 4),
                        notes={"exit_reason": reason, "confidence": conf},
                    )
                    log.info(
                        f"[c2] EXIT  {sym}  reason={reason}  "
                        f"pnl=${pnl:.4f}  portfolio=${portfolio['capital']:.2f}"
                    )
                    del state[sym]
                    changed = True
                else:
                    entry = pos["entry_price"]
                    age   = _age_hours(pos["entry_ts"])
                    pct   = (current_price - entry) / entry
                    log.info(
                        f"[c2] HOLD  {sym}  pct={pct:.2%}  age={age:.1f}h  "
                        f"price={current_price:.4f}"
                    )

            # ── CHECK ENTRY ────────────────────────────────────────────────────
            else:
                if not _entry_conditions(df4h):
                    log.debug(f"[c2] {sym}: no entry signal this cycle")
                    continue

                trade_usd = capital * CAPITAL_PCT
                if trade_usd < 5.0:
                    log.info(f"[c2] {sym}: capital too low (${capital:.2f}) — skip")
                    continue

                capital -= trade_usd
                portfolio["capital"] = capital
                now = datetime.now(timezone.utc).isoformat()

                state[sym] = {
                    "entry_price":   current_price,
                    "entry_ts":      now,
                    "size_usd":      trade_usd,
                    "target_price":  current_price * (1 + TARGET_PCT),
                    "stop_price":    current_price * (1 - STOP_PCT),
                    "last_4h_close": current_price,
                }
                changed = True

                conf = _compute_confidence(df4h)
                record_trade(
                    db_path=DB_PATH, market="crypto", symbol=sym,
                    action="BUY", shares=trade_usd / current_price,
                    price=current_price, signal="C2_BREAKOUT",
                    regime="BULL", pnl=0.0,
                    note=(f"C2 breakout entry: size=${trade_usd:.2f} "
                          f"target={current_price*(1+TARGET_PCT):.4f} "
                          f"stop={current_price*(1-STOP_PCT):.4f}"),
                    strategy="C2_momentum",
                    entry_time=now,
                    size_usd=round(trade_usd, 4),
                    notes={"exit_reason": "", "confidence": conf},
                )
                log.info(
                    f"[c2] ENTRY {sym}  price={current_price:.4f}  "
                    f"size=${trade_usd:.2f}  target={current_price*(1+TARGET_PCT):.4f}  "
                    f"stop={current_price*(1-STOP_PCT):.4f}"
                )

        except Exception as exc:
            log.error(f"[c2] {sym} error: {exc}", exc_info=True)

    if changed:
        _save_state(state)
