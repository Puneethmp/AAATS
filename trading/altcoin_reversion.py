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

# 2026-05-12 TUNE — Phase 1: Z_ENTRY -2.0 → -1.6 (~5% of bars
# vs ~2%, meaningful more fires, still selective). Z_HARD_STOP
# tightened to -2.6 to compensate. Added DOT to universe.
#
# 2026-05-13 TUNE v2 — Replaced naive v1 fixes (fixed sizing, fixed z target)
# with data-aware alternatives:
#   • Vol-adjusted sizing: equalize PnL variance per position, not dollar exposure.
#     base $10/position scaled by VOL_REF/symbol_vol, clamped [$5, $15].
#   • Trailing exit: track max_z during hold. Once max_z reaches Z_TRAILING_MIN
#     (meaningful reversion), exit when current_z drops Z_TRAILING_DROP from max.
#     Captures overshoot in bull regimes AND protects winners that revert before
#     fully mean-reverting. Z_TARGET kept as catch-all for extreme overshoot.
#   • 24h cooldown after stop-out — prevents LUNC-LUNC re-entry pattern.
SYMBOLS = ["SOL/USDT", "LINK/USDT", "AVAX/USDT", "DOT/USDT"]
BTC_SYMBOL = "BTC/USDT"

# ── Sizing (v2: vol-adjusted) ─────────────────────────────────────────────────
# SIZING_MODE  "FIXED": vol-adjusted base POSITION_USD.
#              "PCT":   CAPITAL_PCT × portfolio_capital  (legacy, no vol adj).
SIZING_MODE = "FIXED"
POSITION_USD = 10.0  # base USD per C3 position (pre-vol-adjustment)
CAPITAL_PCT = 0.04  # used only when SIZING_MODE=PCT
MIN_TRADE_USD = 5.0  # below this, fees dominate — refuse to size
MAX_CONCURRENT = 11  # max simultaneous C3 positions (Phase 1 = 11 at $110)

# Vol-adjustment parameters.
# Target: equalize per-position daily PnL variance across the universe.
# size = POSITION_USD × (VOL_REF / symbol_daily_vol), clamped to scale bounds.
# Effect: BNB at 2.5% daily vol gets larger size; FIL at 6% gets smaller size.
VOL_REF = 0.04  # 4% daily — reference vol that anchors POSITION_USD
VOL_LOOKBACK_HOURS = 336  # 14 days × 24h for realized-vol estimate
MIN_SIZE_SCALE = 0.5  # never go below 0.5× POSITION_USD ($5)
MAX_SIZE_SCALE = 1.5  # never go above 1.5× POSITION_USD ($15)

# ── Entry / exit thresholds ───────────────────────────────────────────────────
Z_ENTRY = -1.6  # entry: alt/BTC spread σ below mean  (was -2.0)
Z_HARD_STOP = -2.6  # hard stop: spread diverging further  (was -3.0)
LOOKBACK_BARS = 60  # bars for rolling z-score (60H = 2.5 days on 1H bars)
TIME_STOP_HOURS = 24  # max hold time regardless of z-score
BTC_RSI_MIN = 35  # BTC RSI floor — skip entries in BTC freefall
BTC_DOM_FAST_RISE = 0.008  # skip if BTC dominance rising >0.8% since last cycle
# (units: fraction, NOT percentage points — 0.008 == 0.8%-pt
#  jump in BTC.D since the previous cycle's cached reading).

# Persistent loss-leader denylist (B.2 patch, 2026-05-22).
# Top-5 worst-PNL C3 symbols over the 9-day diagnostic window
# (docs/known_issues/2026-05-21_strategy_c3_altcoin_reversion_diagnostic.md §5).
# 0/8 SELL win rate combined; account for -$4.42 / -$5.63 = ~78% of total C3 loss.
# Skip applies to ENTRY only — held positions can still exit cleanly.
DENYLIST_SYMBOLS = frozenset(
    {
        "OP/USDT",
        "ARB/USDT",
        "PUMP/USDT",
        "FET/USDT",
        "LUNC/USDT",
    }
)

# Z_TARGET as a hard-cap for extreme overshoot. Most exits happen via trailing.
# Set high enough that it rarely fires; primary exit is now trailing logic below.
Z_TARGET = 0.5  # extreme overshoot: take profit immediately

# Trailing exit (v2 — replaces fixed-target exit):
#   Track max_z during the hold. When max_z reaches Z_TRAILING_MIN (we've
#   captured at least ~80% of reversion from -1.6 → -0.3), arm trailing.
#   Then exit when current_z drops Z_TRAILING_DROP from max_z (reversion is
#   reversing — lock in the win).
# Why this is better than fixed Z_TARGET=0:
#   • Captures overshoots: max_z=+0.3, exit at -0.1 → 1.7z gross vs 1.6z fixed.
#   • Protects partial wins: max_z=-0.2, exit at -0.6 → 1.0z vs 0 (never reverts to 0).
#   • Reduces "almost-hit-target-then-reverted-to-stop" outcomes.
Z_TRAILING_MIN = -0.3  # arm trailing once max_z reaches this (80%+ reversion)
Z_TRAILING_DROP = 0.4  # exit when current_z drops this much from max_z

# Cooldown — after a stop-out (z_hard_stop or time_stop with negative pnl) the
# symbol is benched for COOLDOWN_HOURS. Stops the LUNC→LUNC re-entry pattern.
COOLDOWN_HOURS = 24
# A win-exit (z_target or z_trailing) does NOT trigger cooldown.

STATE_FILE = _ROOT / "data" / "altcoin_reversion_state.json"
COOLDOWN_FILE = _ROOT / "data" / "altcoin_reversion_cooldown.json"
BTC_DOM_CACHE_FILE = _ROOT / "data" / "c3_btc_dom_cache.json"
DB_PATH = str(_ROOT / "data" / "paper_trades.db")

# ── Research-bed demotion (2026-06-10) ────────────────────────────────────────
# C3 has NO validated edge (AUDIT/loss_attribution.md; program closed per
# CLAUDE.md). Entries are permanently disabled; the manage-open branch still
# runs so held positions exit cleanly and the book winds down to flat.
# Module retained (not deleted) because backtest tooling + research provenance
# import it. Tests may flip this attribute.
# TEMPORARY (2026-06-27): operator-authorized PAPER-ONLY 7-day observation
# window — flipped False; box auto-reverts to True at the deadline. NOT a
# strategy reopen. See docs/decisions/2026-06-27_paper_only_entry_resume.md.
ENTRIES_DISABLED = False

# Honest-PnL cost layer (2026-06-10, AUDIT/structural_fixes.md FIX 1):
# C3 fills are raw prices, so realized PnL is written net of fees + modeled
# slippage on both legs (spot taker, analytics/cost_model.py rates).
from analytics.cost_model import round_trip_cost as _round_trip_cost  # noqa: E402

# Unified positions ledger wiring (Q1-Q4=A, ledger commit 3/3 2026-05-21).
# Flag is read ONCE at module import per Q4=A; flips require container restart.
from foundation import state_bridge as _state_bridge  # noqa: E402

STRATEGY_ID = "C3_altcoin_reversion"
MARKET = "crypto"
_USE_UNIFIED_LEDGER = _state_bridge.is_unified_ledger_enabled()


# ── State helpers ─────────────────────────────────────────────────────────────
def _load_state() -> dict[str, Any]:
    if _USE_UNIFIED_LEDGER:
        return _state_bridge.load_state(
            STRATEGY_ID, MARKET, STATE_FILE, use_unified=True
        )
    try:
        if STATE_FILE.exists():
            raw = STATE_FILE.read_text(encoding="utf-8")
            return json.loads(raw)
    except Exception as exc:
        log.warning("[c3] state file unreadable (%s) — starting fresh", exc)
    return {}


def _save_state(state: dict[str, Any]) -> None:
    if _USE_UNIFIED_LEDGER:
        _state_bridge.save_state(
            STRATEGY_ID, MARKET, state, STATE_FILE, use_unified=True
        )
        return
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


# ── Cooldown helpers (2026-05-13) ─────────────────────────────────────────────
def _load_cooldown() -> dict[str, str]:
    """Load symbol → cooldown_until_iso mapping."""
    try:
        if COOLDOWN_FILE.exists():
            raw = COOLDOWN_FILE.read_text(encoding="utf-8")
            return json.loads(raw)
    except Exception as exc:
        log.warning("[c3] cooldown file unreadable (%s) — starting fresh", exc)
    return {}


def _save_cooldown(cooldown: dict[str, str]) -> None:
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOLDOWN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cooldown, indent=2, default=str), encoding="utf-8")
    tmp.replace(COOLDOWN_FILE)


def _is_cooling_down(symbol: str, cooldown: dict[str, str]) -> tuple[bool, float]:
    """Return (in_cooldown, hours_remaining)."""
    until_iso = cooldown.get(symbol)
    if not until_iso:
        return False, 0.0
    try:
        until = datetime.fromisoformat(until_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if now >= until:
            return False, 0.0
        hours_left = (until - now).total_seconds() / 3600
        return True, hours_left
    except Exception:
        return False, 0.0


def _set_cooldown(
    symbol: str, cooldown: dict[str, str], hours: float = COOLDOWN_HOURS
) -> None:
    """Place symbol on the bench for `hours`. Modifies cooldown dict in place."""
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    cooldown[symbol] = until.isoformat()


# ── BTC.D delta cache (B.2 patch, 2026-05-22) ────────────────────────────────
def _load_btc_dom_cache() -> float | None:
    """Last cycle's BTC dominance reading (or None on first run / unreadable)."""
    try:
        if BTC_DOM_CACHE_FILE.exists():
            raw = json.loads(BTC_DOM_CACHE_FILE.read_text(encoding="utf-8"))
            v = raw.get("prev_btc_dom")
            return float(v) if v is not None else None
    except Exception as exc:
        log.warning("[c3] btc_dom cache unreadable (%s) — first-run semantics", exc)
    return None


def _save_btc_dom_cache(btc_dom: float) -> None:
    """Persist the current BTC.D reading for next cycle's delta computation."""
    BTC_DOM_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "prev_btc_dom": float(btc_dom),
        "prev_ts": datetime.now(timezone.utc).isoformat(),
    }
    tmp = BTC_DOM_CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(BTC_DOM_CACHE_FILE)


def _prune_cooldown(cooldown: dict[str, str]) -> bool:
    """Drop expired entries. Returns True if any change made."""
    now = datetime.now(timezone.utc)
    drop = []
    for sym, until_iso in cooldown.items():
        try:
            until = datetime.fromisoformat(until_iso.replace("Z", "+00:00"))
            if now >= until:
                drop.append(sym)
        except Exception:
            drop.append(sym)
    for sym in drop:
        del cooldown[sym]
    return bool(drop)


# ── Vol estimation helper (2026-05-13 v2) ─────────────────────────────────────
def _realized_daily_vol(
    df: pd.DataFrame, lookback_hours: int = VOL_LOOKBACK_HOURS
) -> float | None:
    """
    Estimate symbol's annualized-to-daily realized vol from 1H bars.

    Returns daily-equivalent stdev of log returns (e.g. 0.04 = 4%/day).
    Returns None when data is insufficient or invariant — caller falls back
    to no-adjustment.
    """
    try:
        closes = df["close"].values[-(lookback_hours + 5) :]
        if len(closes) < 50:
            return None
        log_ret = np.diff(np.log(closes))
        hourly_std = float(np.std(log_ret, ddof=1))
        if hourly_std <= 0 or not np.isfinite(hourly_std):
            return None
        return hourly_std * float(np.sqrt(24))  # scale hourly → daily
    except Exception as exc:
        log.debug("[c3] realized_vol error: %s", exc)
        return None


# ── Position-sizing helper (2026-05-13 v2: vol-adjusted) ──────────────────────
def _compute_trade_size(
    capital: float,
    open_positions: int,
    symbol_vol: float | None = None,
) -> tuple[float, str]:
    """
    Determine USD size for next C3 entry.

    Vol-adjusted sizing: size = POSITION_USD × (VOL_REF / symbol_vol),
    clamped to [MIN_SIZE_SCALE, MAX_SIZE_SCALE] × POSITION_USD.

    When symbol_vol is None (data insufficient), falls back to POSITION_USD
    without adjustment.

    Returns (size_usd, reason). size_usd=0 means refuse to size.
    """
    if open_positions >= MAX_CONCURRENT:
        return 0.0, f"max_concurrent_{open_positions}/{MAX_CONCURRENT}"

    if SIZING_MODE == "FIXED":
        base = POSITION_USD
        if symbol_vol is not None and symbol_vol > 1e-6:
            scale = VOL_REF / symbol_vol
            scale = max(MIN_SIZE_SCALE, min(MAX_SIZE_SCALE, scale))
            size = base * scale
        else:
            size = base  # no-adjustment fallback
    else:  # PCT mode (legacy, no vol adjustment)
        size = capital * CAPITAL_PCT

    if size < MIN_TRADE_USD:
        return 0.0, f"size_below_min_${size:.2f}<${MIN_TRADE_USD:.2f}"
    if size > capital:
        return 0.0, f"size_above_capital_${size:.2f}>${capital:.2f}"

    return round(size, 2), "ok"


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


def _compute_z_score(
    alt_df: pd.DataFrame, btc_df: pd.DataFrame, lookback: int = LOOKBACK_BARS
) -> float | None:
    """
    Compute z-score of log(ALT_close / BTC_close) over the last `lookback` bars.
    Returns None if insufficient data.
    """
    try:
        # Align on timestamps
        alt_closes = alt_df["close"].values[-lookback - 10 :]
        btc_closes = btc_df["close"].values[-lookback - 10 :]
        n = min(len(alt_closes), len(btc_closes))
        if n < lookback:
            return None

        alt_c = alt_closes[-n:]
        btc_c = btc_closes[-n:]

        # Compute log ratio
        ratio = np.log(alt_c / btc_c)

        # Rolling z-score using last `lookback` bars
        window = ratio[-lookback:]
        mean = window.mean()
        std = window.std(ddof=1)
        if std < 1e-8:
            return None

        z = float((ratio[-1] - mean) / std)
        return z
    except Exception as exc:
        log.debug("[c3] z-score compute error: %s", exc)
        return None


# ── Entry/exit logic ─────────────────────────────────────────────────────────
def _entry_allowed(
    btc_df: pd.DataFrame,
    regime: str,
    btc_dom_delta: float | None = None,
) -> bool:
    """
    Pre-flight checks before any C3 entry.
    Returns False if macro conditions are unfavourable.

    Args:
        btc_dom_delta: BTC dominance change since the previous cycle, as a
            percentage-point delta (so 0.8 means BTC.D rose 0.8 pp). When
            >= BTC_DOM_FAST_RISE * 100, refuse entry — BTC.D fast-rise is
            the documented "alt season over" signal (constant declared at
            :77 but never read pre-2026-05-22). None disables the check
            (e.g. first cycle after a restart, or test paths).
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

    # BTC dominance fast-rise: "alt season over" filter.
    # BTC_DOM_FAST_RISE is declared as a fraction (0.008 == 0.8 pp); the
    # caller-supplied delta is in percentage points, so we compare against
    # BTC_DOM_FAST_RISE * 100.
    if btc_dom_delta is not None and btc_dom_delta >= (BTC_DOM_FAST_RISE * 100):
        log.info(
            "[c3] BTC.D rising fast (+%.3f pp >= %.3f pp) — skip entry",
            btc_dom_delta,
            BTC_DOM_FAST_RISE * 100,
        )
        return False

    return True


def _should_exit(pos: dict, current_z: float) -> tuple[bool, str]:
    """
    Evaluate exit conditions for an open C3 position.

    Exit priority (first match wins):
      1. z_overshoot     — current_z >= Z_TARGET (extreme overshoot, take profit)
      2. z_trailing      — max_z >= Z_TRAILING_MIN AND (max_z - current_z) >= Z_TRAILING_DROP
                           (we captured meaningful reversion and now it's reverting back)
      3. z_hard_stop     — current_z <= Z_HARD_STOP (divergence)
      4. time_stop_24h   — held too long regardless of z

    Returns (exit_now, reason).
    """
    # 1. Extreme overshoot — take profit immediately (rare)
    if current_z >= Z_TARGET:
        return True, "z_overshoot"

    # 2. Trailing exit — captured good reversion, now reverting back
    max_z = pos.get("max_z", pos.get("entry_z", current_z))
    if max_z >= Z_TRAILING_MIN and (max_z - current_z) >= Z_TRAILING_DROP:
        return True, "z_trailing"

    # 3. Hard stop — spread diverged further
    if current_z <= Z_HARD_STOP:
        return True, "z_hard_stop"

    # 4. Time stop — max hold exceeded
    age_h = _age_hours(pos["entry_ts"])
    if age_h >= TIME_STOP_HOURS:
        return True, f"time_stop_{TIME_STOP_HOURS}h"

    return False, ""


# ── DB record helper ──────────────────────────────────────────────────────────
def _record(
    symbol: str,
    action: str,
    price: float,
    size_usd: float,
    pnl: float = 0.0,
    entry_time: str | None = None,
    exit_time: str | None = None,
    pnl_pct: float | None = None,
    z_score: float = 0.0,
    exit_reason: str = "",
    shares: float | None = None,
    gross_pnl: float | None = None,
    costs: float | None = None,
) -> None:
    """Persist the trade row to paper_trades.db.

    Raises on any DB failure — the caller (run_altcoin_reversion_crypto)
    MUST skip the corresponding state mutation when this raises, or the
    strategy state file will hold an entry with no matching ledger row
    and the reconciler will halt the cycle. The 2026-05-23 phantom-ENA
    incident was caused by an earlier swallow-and-log here; see
    tests/test_orphan_position_prevention.py for the regression pin.
    """
    from execution.paper_trader import record_trade

    # SELL must record the same shares that the BUY row stored, otherwise
    # paper_trades SUM(BUY) - SUM(SELL) leaves residual dust per closed
    # position. Caller passes the entry-derived shares for SELL. BUY path
    # falls back to size_usd/price (price IS entry price there, correct).
    recorded_shares = (
        float(shares) if shares is not None else round(size_usd / max(price, 1e-9), 8)
    )
    record_trade(
        db_path=DB_PATH,
        market="crypto",
        symbol=symbol,
        action=action,
        shares=recorded_shares,
        price=price,
        signal="C3_ALT_REVERSION",
        regime="RANGE_OR_BULL",
        risk_action="ALLOW",
        pnl=pnl,
        note=f"C3 {action} z={z_score:.3f}",
        strategy="C3_altcoin_reversion",
        entry_time=entry_time,
        exit_time=exit_time,
        pnl_pct=pnl_pct,
        size_usd=round(size_usd, 4),
        notes={
            "z_score": round(z_score, 4),
            "exit_reason": exit_reason,
            "confidence": 0.70,  # C3 has no ML gate yet; fixed prior
            # Honest-PnL audit trail: pnl column is NET; gross + costs here.
            **(
                {"gross_pnl": round(gross_pnl, 6), "costs": round(costs, 6)}
                if gross_pnl is not None and costs is not None
                else {}
            ),
        },
    )


# ── Public runner ──────────────────────────────────────────────────────────────
def run_altcoin_reversion_crypto(
    portfolio: dict,
    fetch_hourly_fn,
    symbols: list[str] | None = None,
    full_positions: dict | None = None,
    full_portfolio: dict | None = None,
    btc_dom_now: float | None = None,
) -> None:
    """
    Main entry point called from live_paper_runner.py each crypto cycle.

    Args:
        portfolio:      Crypto sub-portfolio dict (mutable — capital updated in place).
        fetch_hourly_fn: Function(symbol) -> pd.DataFrame | None (1H OHLCV).
        symbols:        Optional override of trade universe. When provided,
                        ONLY these symbols are evaluated this cycle. None = use
                        hardcoded SYMBOLS default (backward compat).
        full_positions: Full positions dict {"crypto": {...}, "india": {...}}.
                        Required for kill-switch gate (B' helper). When None
                        (test/back-compat callers), the gate is bypassed.
        full_portfolio: Full portfolio dict {"crypto": {...}, "india": {...}}.
                        Same role as full_positions.
        btc_dom_now:    Current cycle's BTC dominance reading (percentage,
                        e.g. 56.3). Used with the persisted previous-cycle
                        cache to compute btc_dom_delta and gate entries via
                        BTC_DOM_FAST_RISE. None disables the check (test /
                        back-compat callers; first cycle after restart).
    """
    # Resolve kill-switch helper once per cycle. Imported lazily to avoid the
    # circular trading.live_paper_runner <-> trading.altcoin_reversion edge
    # when this module is loaded under pytest fixtures that don't go through
    # the runner.
    _gate_check = None
    _exit_gate_check = None
    if full_positions is not None and full_portfolio is not None:
        try:
            from trading.live_paper_runner import (
                apply_kill_switch_gate as _gate_check,
                apply_kill_switch_exit_gate as _exit_gate_check,
            )
        except Exception as exc:
            log.warning(
                "[c3] kill-switch helper unavailable (%s) — proceeding ungated", exc
            )
            _gate_check = None
            _exit_gate_check = None
    state = _load_state()
    cooldown = _load_cooldown()
    changed = False
    cooldown_changed = _prune_cooldown(cooldown)
    capital = portfolio.get("capital", 0.0)

    if ENTRIES_DISABLED:
        log.info(
            "[c3] DEMOTED (research-bed 2026-06-10): entries disabled — "
            "exit-only wind-down, %d open",
            len(state),
        )

    # BTC.D delta vs previous cycle (B.2 patch, 2026-05-22).
    # None semantics: first cycle after a (re)deploy, no cache → no delta →
    # _entry_allowed treats this as "no signal", filter disabled. Subsequent
    # cycles compute a real delta and gate accordingly.
    btc_dom_delta: float | None = None
    if btc_dom_now is not None:
        _prev_btc_dom = _load_btc_dom_cache()
        if _prev_btc_dom is not None:
            btc_dom_delta = float(btc_dom_now) - _prev_btc_dom
        _save_btc_dom_cache(btc_dom_now)

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

    universe = symbols if symbols is not None else SYMBOLS

    # Also evaluate exits for any held position outside the per-cycle universe.
    # The runner's scanner-driven c3_picks excludes held symbols by design
    # (allocator.py:167), which would otherwise orphan exit evaluation: once
    # a held symbol drops off c3_picks, _should_exit never runs for it and
    # time_stop_24h becomes inert. Entry branch is gated by `pos is None`, so
    # held_outside symbols only exercise the manage-open branch — no risk of
    # an unintended re-entry.
    held_outside = sorted(set(state) - set(universe))
    if held_outside:
        log.info(
            "[c3] also evaluating %d held position(s) outside picks: %s",
            len(held_outside),
            held_outside,
        )
    to_evaluate = list(universe) + held_outside

    open_count = len(state)
    if cooldown:
        cooling = [f"{s}({_is_cooling_down(s, cooldown)[1]:.1f}h)" for s in cooldown]
        log.info("[c3] cooldown active for: %s", ", ".join(cooling))

    for sym in to_evaluate:
        try:
            alt_df = fetch_hourly_fn(sym)
            if alt_df is None or len(alt_df) < LOOKBACK_BARS + 10:
                log.debug("[c3] %s: insufficient data", sym)
                continue

            current_price = float(alt_df["close"].iloc[-1])
            current_z = _compute_z_score(alt_df, btc_df)

            if current_z is None:
                log.debug("[c3] %s: z-score unavailable", sym)
                continue

            log.debug("[c3] %s  z=%.3f  price=%.4f", sym, current_z, current_price)

            pos = state.get(sym)

            # ── Manage open position ──────────────────────────────────────────
            if pos is not None:
                # v2: track max_z reached during the hold (for trailing exit).
                prev_max = pos.get("max_z", pos.get("entry_z", current_z))
                new_max = max(prev_max, current_z)
                if new_max > prev_max:
                    pos["max_z"] = new_max
                    state[sym] = pos
                    changed = True

                exit_now, reason = _should_exit(pos, current_z)
                if exit_now:
                    # EXIT gate (session 8, 2026-05-23): only catastrophic
                    # HALT_ALL blocks. Per-market HALT_MARKET (drawdown <=
                    # -15%) and operator halt allow the SELL through —
                    # those are 'block new entries' channels, not 'block
                    # all activity' channels. See
                    # docs/known_issues/2026-05-23_kill_trigger_investigation.md.
                    if _exit_gate_check is not None:
                        _allowed, _kill_reason = _exit_gate_check(
                            "crypto",
                            sym,
                            current_price,
                            full_positions,
                            full_portfolio,
                        )
                        if not _allowed:
                            log.info(
                                "[c3] %s: SKIP SELL — HALT_ALL active (%s)",
                                sym,
                                _kill_reason,
                            )
                            continue

                    entry = pos["entry_price"]
                    size = pos["size_usd"]
                    # Honest-PnL (2026-06-10, AUDIT/structural_fixes.md FIX 1):
                    # the ledger row is NET of round-trip costs. C3 fills are
                    # raw prices, so both fees AND modeled slippage apply.
                    gross = size * (current_price - entry) / entry
                    _exit_notional = size * current_price / max(entry, 1e-9)
                    _costs = _round_trip_cost(size, _exit_notional).total
                    pnl = gross - _costs
                    pnl_pct = round(pnl / size * 100, 4) if size else None
                    exit_ts = datetime.now(timezone.utc).isoformat()

                    # 2026-05-23 phantom-ENA fix: write the SELL ledger
                    # row FIRST. If it fails, we LEAVE the position open
                    # (state + capital untouched) so the next cycle can
                    # retry. Better to hold a position one extra cycle
                    # than to lose track of it.
                    try:
                        _record(
                            symbol=sym,
                            action="SELL",
                            price=current_price,
                            size_usd=size,
                            pnl=pnl,
                            entry_time=pos["entry_ts"],
                            exit_time=exit_ts,
                            pnl_pct=pnl_pct,
                            z_score=current_z,
                            exit_reason=reason,
                            shares=round(
                                pos["size_usd"] / max(pos["entry_price"], 1e-9), 8
                            ),
                            gross_pnl=gross,
                            costs=_costs,
                        )
                    except Exception as exc:
                        log.error(
                            "[c3] %s: SELL ABORTED — record_trade failed (%s); "
                            "position held, will retry next cycle",
                            sym,
                            exc,
                        )
                        continue

                    capital += size + pnl
                    portfolio["capital"] = capital
                    log.info(
                        "[c3] EXIT  %s  reason=%s  z=%.3f  "
                        "pnl=$%.4f (%.2f%%)  portfolio=$%.2f",
                        sym,
                        reason,
                        current_z,
                        pnl,
                        pnl_pct or 0.0,
                        capital,
                    )
                    del state[sym]
                    open_count -= 1
                    changed = True

                    # 2026-05-13 v2: cooldown after stop-out (hard stop or
                    # money-losing time stop). Win exits (z_overshoot,
                    # z_trailing) do NOT cool the symbol down.
                    is_stop_out = reason == "z_hard_stop" or (
                        reason.startswith("time_stop") and pnl < 0
                    )
                    if is_stop_out:
                        _set_cooldown(sym, cooldown)
                        cooldown_changed = True
                        log.info(
                            "[c3] cooldown %s for %.0fh after %s (pnl=%.2f%%)",
                            sym,
                            COOLDOWN_HOURS,
                            reason,
                            pnl_pct or 0.0,
                        )
                else:
                    age_h = _age_hours(pos["entry_ts"])
                    pct = (current_price - pos["entry_price"]) / pos["entry_price"]
                    log.info(
                        "[c3] HOLD  %s  z=%.3f  pct=%+.2f%%  age=%.1fh",
                        sym,
                        current_z,
                        pct * 100,
                        age_h,
                    )

            # ── Check entry ───────────────────────────────────────────────────
            else:
                # Research-bed demotion (2026-06-10): no new entries, ever.
                # Logged once per cycle above; skip silently per-symbol.
                if ENTRIES_DISABLED:
                    continue

                # Persistent denylist (B.2 patch, 2026-05-22). Skip ENTRY
                # only — already-open positions still take the manage-open
                # branch above, so SELLs are unimpeded.
                if sym in DENYLIST_SYMBOLS:
                    log.info("[c3] %s: SKIP entry — denylisted (B.2 loss-leader)", sym)
                    continue

                if current_z > Z_ENTRY:
                    log.debug(
                        "[c3] %s: z=%.3f > %.1f threshold — no entry",
                        sym,
                        current_z,
                        Z_ENTRY,
                    )
                    continue

                # 2026-05-13: cooldown check — skip symbols recently stopped out.
                cooling, hours_left = _is_cooling_down(sym, cooldown)
                if cooling:
                    log.info(
                        "[c3] %s: SKIP entry — cooldown %.1fh remaining",
                        sym,
                        hours_left,
                    )
                    continue

                if not _entry_allowed(btc_df, btc_regime, btc_dom_delta=btc_dom_delta):
                    continue

                # 2026-05-13 v2: vol-adjusted sizing. Equalizes per-position
                # daily PnL variance across the universe (rather than dollar
                # exposure). Falls back to base POSITION_USD if vol unavailable.
                symbol_vol = _realized_daily_vol(alt_df)
                trade_usd, reason = _compute_trade_size(capital, open_count, symbol_vol)
                if trade_usd <= 0:
                    log.info("[c3] %s: SKIP entry — %s", sym, reason)
                    continue

                # Kill-switch gate (B') — block BUY emission BEFORE any state
                # mutation, DB write, or capital adjustment. If tripped, the
                # entry is skipped this cycle (re-evaluated next cycle).
                if _gate_check is not None:
                    _allowed, _kill_reason = _gate_check(
                        "crypto",
                        sym,
                        current_price,
                        full_positions,
                        full_portfolio,
                    )
                    if not _allowed:
                        log.info(
                            "[c3] %s: SKIP BUY — kill switch active (%s)",
                            sym,
                            _kill_reason,
                        )
                        continue

                entry_ts = datetime.now(timezone.utc).isoformat()

                # 2026-05-23 phantom-ENA fix: write the ledger row FIRST.
                # State + capital are mutated ONLY on a successful DB
                # insert, so a record_trade failure cannot leave an
                # orphan position in altcoin_reversion_state.json.
                try:
                    _record(
                        symbol=sym,
                        action="BUY",
                        price=current_price,
                        size_usd=trade_usd,
                        entry_time=entry_ts,
                        z_score=current_z,
                        exit_reason="",
                    )
                except Exception as exc:
                    log.error(
                        "[c3] %s: BUY ABORTED — record_trade failed (%s); "
                        "no state mutation, no capital deduction",
                        sym,
                        exc,
                    )
                    continue

                capital -= trade_usd
                portfolio["capital"] = capital
                state[sym] = {
                    "entry_price": current_price,
                    "entry_ts": entry_ts,
                    "size_usd": trade_usd,
                    "entry_z": current_z,
                    "max_z": current_z,  # v2: trailing-exit seed
                    "symbol_vol": symbol_vol,  # v2: stored for observability
                }
                open_count += 1
                changed = True

                vol_str = f"{symbol_vol:.3f}" if symbol_vol is not None else "n/a"
                log.info(
                    "[c3] ENTRY %s  z=%.3f  price=%.4f  vol=%s  "
                    "size=$%.2f  open=%d/%d  portfolio=$%.2f",
                    sym,
                    current_z,
                    current_price,
                    vol_str,
                    trade_usd,
                    open_count,
                    MAX_CONCURRENT,
                    capital,
                )

        except Exception as exc:
            log.error("[c3] %s cycle error: %s", sym, exc, exc_info=True)

    if changed:
        _save_state(state)
    if cooldown_changed:
        _save_cooldown(cooldown)
