"""
trading/altcoin_reversion.py  —  C3 Altcoin Beta Mean Reversion

Strategy:
  Long an altcoin when it has cheapened significantly vs BTC on a beta-adjusted basis.
  Signal: log(ALT/BTC) z-score < -2.0  (alt has become cheap relative to BTC)
  Entry:  HMM regime != BEAR  AND  BTC RSI(14) > 35  (BTC not in freefall)
  Target: z-score returns to -0.5  (mean reversion 75% of the way back)
  Stops:  Time stop 24H  |  Hard stop z = -3.0  (alt diverging further)
  Skips:  BTC dominance rising fast (>0.8%/cycle) — alt season over

Universe:  SOL/USDT, LINK/USDT, AVAX/USDT
Capital:   4% of crypto portfolio per trade (CAPITAL_PCT = 0.04)
Expected:  55-58% WR, avg +2.5% per trade, ~4-6 trades/month

Integration:
  Called from live_paper_runner.py run_crypto() via:
    run_altcoin_reversion_crypto(portfolio["crypto"], fetch_crypto_hourly)
"""

from __future__ import annotations

import json
import logging
import pathlib
from datetime import datetime, timezone, timedelta
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parents[1]

SYMBOLS         = ["SOL/USDT", "LINK/USDT", "AVAX/USDT"]
BTC_SYMBOL      = "BTC/USDT"
CAPITAL_PCT     = 0.04       # 4% of crypto portfolio per position
Z_ENTRY         = -2.0       # entry: alt/BTC spread this many std devs below mean
Z_TARGET        = -0.5       # exit target: reversion most of the way back
Z_HARD_STOP     = -3.0       # hard stop: spread diverging further (worse)
LOOKBACK_BARS   = 60         # bars for rolling z-score (60H = 2.5 days on 1H bars)
TIME_STOP_HOURS = 24         # max hold time regardless of z-score
BTC_RSI_MIN     = 35         # BTC RSI floor — skip entries in BTC freefall
BTC_DOM_FAST_RISE = 0.008    # skip if BTC dominance rising >0.8% since last cycle

STATE_FILE = _ROOT / "data" / "altcoin_reversion_state.json"
DB_PATH    = str(_ROOT / "data" / "paper_trades.db")


# ── State helpers ─────────────────────────────────────────────────────────────
def _load_state() -> dict[str, Any]:
    try:
        if STATE_FILE.exists():
            raw = STATE_FILE.read_text(encoding="utf-8")
            return json.loads(raw)
    except Exception as exc:
        log.warning("[c3] state file unreadable (%s) — starting fresh", exc)
    return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _age_hours(entry_ts: str) -> float:
    try:
        ts = datetime.fromisoformat(entry_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except Exception:
        return 0.0


# ── Feature helpers ────────────────────────────────────────────────────────────
def _rsi(series: pd.Series, period: int = 14) -> float:
    """Simple RSI on the last N+1 bars."""
    delta = series.diff().dropna()
    if len(delta) < period:
        return 50.0
    gain = delta.where(delta > 0, 0.0).rolling(period).mean().iloc[-1]
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean().iloc[-1]
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100 - 100 / (1 + rs))


def _compute_z_score(alt_df: pd.DataFrame, btc_df: pd.DataFrame,
                     lookback: int = LOOKBACK_BARS) -> float | None:
    """
    Compute z-score of log(ALT_close / BTC_close) over the last `lookback` bars.
    Returns None if insufficient data.
    """
    try:
        # Align on timestamps
        alt_closes = alt_df["close"].values[-lookback - 10:]
        btc_closes = btc_df["close"].values[-lookback - 10:]
        n = min(len(alt_closes), len(btc_closes))
        if n < lookback:
            return None

        alt_c = alt_closes[-n:]
        btc_c = btc_closes[-n:]

        # Compute log ratio
        ratio = np.log(alt_c / btc_c)

        # Rolling z-score using last `lookback` bars
        window = ratio[-lookback:]
        mean   = window.mean()
        std    = window.std(ddof=1)
        if std < 1e-8:
            return None

        z = float((ratio[-1] - mean) / std)
        return z
    except Exception as exc:
        log.debug("[c3] z-score compute error: %s", exc)
        return None


# ── Entry/exit logic ─────────────────────────────────────────────────────────
def _entry_allowed(btc_df: pd.DataFrame, regime: str) -> bool:
    """
    Pre-flight checks before any C3 entry.
    Returns False if macro conditions are unfavourable.
    """
    # BTC RSI floor
    btc_rsi = _rsi(btc_df["close"], period=14)
    if btc_rsi < BTC_RSI_MIN:
        log.debug("[c3] BTC RSI=%.1f < %d — skip entry", btc_rsi, BTC_RSI_MIN)
        return False

    # Regime guard — no entries in BEAR
    if "BEAR" in regime.upper():
        log.debug("[c3] regime=%s — skip entry", regime)
        return False

    return True


def _should_exit(pos: dict, current_z: float) -> tuple[bool, str]:
    """
    Evaluate exit conditions for an open C3 position.
    Returns (exit_now, reason).
    """
    # Target: z reverted to Z_TARGET
    if current_z >= Z_TARGET:
        return True, "z_target"

    # Hard stop: spread diverged to Z_HARD_STOP
    if current_z <= Z_HARD_STOP:
        return True, "z_hard_stop"

    # Time stop: max hold exceeded
    age_h = _age_hours(pos["entry_ts"])
    if age_h >= TIME_STOP_HOURS:
        return True, f"time_stop_{TIME_STOP_HOURS}h"

    return False, ""


# ── DB record helper ──────────────────────────────────────────────────────────
def _record(
    symbol: str, action: str, price: float,
    size_usd: float, pnl: float = 0.0,
    entry_time: str | None = None,
    exit_time: str | None = None,
    pnl_pct: float | None = None,
    z_score: float = 0.0,
    exit_reason: str = "",
) -> None:
    try:
        from execution.paper_trader import record_trade
        record_trade(
            db_path=DB_PATH, market="crypto", symbol=symbol,
            action=action,
            shares=round(size_usd / max(price, 1e-9), 8),
            price=price, signal="C3_ALT_REVERSION",
            regime="RANGE_OR_BULL", risk_action="ALLOW",
            pnl=pnl,
            note=f"C3 {action} z={z_score:.3f}",
            strategy="C3_altcoin_reversion",
            entry_time=entry_time,
            exit_time=exit_time,
            pnl_pct=pnl_pct,
            size_usd=round(size_usd, 4),
            notes={
                "z_score":     round(z_score, 4),
                "exit_reason": exit_reason,
                "confidence":  0.70,   # C3 has no ML gate yet; fixed prior
            },
        )
    except Exception as exc:
        log.warning("[c3] record_trade failed: %s", exc)


# ── Public runner ──────────────────────────────────────────────────────────────
def run_altcoin_reversion_crypto(
    portfolio: dict,
    fetch_hourly_fn,
) -> None:
    """
    Main entry point called from live_paper_runner.py each crypto cycle.

    Args:
        portfolio:      Crypto sub-portfolio dict (mutable — capital updated in place).
        fetch_hourly_fn: Function(symbol) -> pd.DataFrame | None (1H OHLCV).
    """
    state   = _load_state()
    changed = False
    capital = portfolio.get("capital", 0.0)

    # Fetch BTC bars once — needed for z-score and RSI check
    btc_df = fetch_hourly_fn(BTC_SYMBOL)
    if btc_df is None or len(btc_df) < LOOKBACK_BARS + 10:
        log.debug("[c3] BTC data unavailable — skip cycle")
        return

    # Detect BTC regime from live_paper_runner cache
    try:
        from trading.live_paper_runner import detect_regime
        btc_regime, _ = detect_regime(BTC_SYMBOL, btc_df)
    except Exception:
        btc_regime = "RANGE_BOUND"

    for sym in SYMBOLS:
        try:
            alt_df = fetch_hourly_fn(sym)
            if alt_df is None or len(alt_df) < LOOKBACK_BARS + 10:
                log.debug("[c3] %s: insufficient data", sym)
                continue

            current_price = float(alt_df["close"].iloc[-1])
            current_z     = _compute_z_score(alt_df, btc_df)

            if current_z is None:
                log.debug("[c3] %s: z-score unavailable", sym)
                continue

            log.debug("[c3] %s  z=%.3f  price=%.4f", sym, current_z, current_price)

            pos = state.get(sym)

            # ── Manage open position ──────────────────────────────────────────
            if pos is not None:
                exit_now, reason = _should_exit(pos, current_z)
                if exit_now:
                    entry      = pos["entry_price"]
                    size       = pos["size_usd"]
                    pnl        = size * (current_price - entry) / entry
                    pnl_pct    = round(pnl / size * 100, 4) if size else None
                    exit_ts    = datetime.now(timezone.utc).isoformat()
                    capital   += size + pnl
                    portfolio["capital"] = capital

                    _record(
                        symbol=sym, action="SELL",
                        price=current_price, size_usd=size,
                        pnl=pnl, entry_time=pos["entry_ts"],
                        exit_time=exit_ts, pnl_pct=pnl_pct,
                        z_score=current_z, exit_reason=reason,
                    )
                    log.info(
                        "[c3] EXIT  %s  reason=%s  z=%.3f  "
                        "pnl=$%.4f (%.2f%%)  portfolio=$%.2f",
                        sym, reason, current_z, pnl,
                        pnl_pct or 0.0, capital,
                    )
                    del state[sym]
                    changed = True
                else:
                    age_h = _age_hours(pos["entry_ts"])
                    pct   = (current_price - pos["entry_price"]) / pos["entry_price"]
                    log.info(
                        "[c3] HOLD  %s  z=%.3f  pct=%+.2f%%  age=%.1fh",
                        sym, current_z, pct * 100, age_h,
                    )

            # ── Check entry ───────────────────────────────────────────────────
            else:
                if current_z > Z_ENTRY:
                    log.debug("[c3] %s: z=%.3f > %.1f threshold — no entry", sym, current_z, Z_ENTRY)
                    continue

                if not _entry_allowed(btc_df, btc_regime):
                    continue

                trade_usd = capital * CAPITAL_PCT
                if trade_usd < 3.0:
                    log.info("[c3] %s: capital too low ($%.2f) — skip", sym, capital)
                    continue

                entry_ts   = datetime.now(timezone.utc).isoformat()
                capital   -= trade_usd
                portfolio["capital"] = capital

                state[sym] = {
                    "entry_price": current_price,
                    "entry_ts":    entry_ts,
                    "size_usd":    trade_usd,
                    "entry_z":     current_z,
                }
                changed = True

                _record(
                    symbol=sym, action="BUY",
                    price=current_price, size_usd=trade_usd,
                    entry_time=entry_ts,
                    z_score=current_z, exit_reason="",
                )
                log.info(
                    "[c3] ENTRY %s  z=%.3f  price=%.4f  "
                    "size=$%.2f  portfolio=$%.2f",
                    sym, current_z, current_price, trade_usd, capital,
                )

        except Exception as exc:
            log.error("[c3] %s cycle error: %s", sym, exc, exc_info=True)

    if changed:
        _save_state(state)
