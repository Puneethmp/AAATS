"""
AAATS Statistical Arbitrage — Enhanced Pairs Trading Engine (C1)
================================================================
Market-neutral mean-reversion on cointegrated pairs.

C1 Enhanced (2026-05-07):
  - 30-bar z-score (was 20), entry |z|>1.8 (was 2.0), exit |z|<0.35 (was 0.5)
  - Time stop: 48H max hold (crypto), 5H (India intraday)
  - Hard stop: z reaches +-2.8 (spread blowing out, cut losses)
  - Pre-entry health gate: weekly Engle-Granger + 14-day rolling correlation
  - Pair health cache: _HEALTH_FILE, refreshed weekly (not every cycle)

State persists in data/stat_arb_state.json.
Health cache in data/stat_arb_health.json.

Usage (called from live_paper_runner.py):
    from trading.stat_arb import run_stat_arb_crypto, run_stat_arb_india
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

_ROOT        = Path(__file__).resolve().parent.parent
_STATE_FILE  = _ROOT / "data" / "stat_arb_state.json"
_HEALTH_FILE = _ROOT / "data" / "stat_arb_health.json"
_DB_PATH     = str(_ROOT / "data" / "paper_trades.db")

log = logging.getLogger("trading.stat_arb")


# == Pair definitions ==========================================================

class Pair(NamedTuple):
    long_sym:            str    # symbol to BUY when spread is low
    short_sym:           str    # symbol to SELL when spread is low
    market:              str    # "crypto" or "india"
    window:              int    # rolling z-score window (bars)
    entry_z:             float  # open position when |z| > this
    exit_z:              float  # close position when |z| < this
    alloc_pct:           float  # fraction of market capital per leg
    time_stop_hours:     int    # max hours to hold before forced exit
    hard_stop_z:         float  # force exit if |z| reaches this (spread blowout)
    min_correlation_14d: float  # skip entry if 14-day rolling corr < this
    cointegration_p_max: float  # skip entry if Engle-Granger p-value > this


PAIRS = [
    Pair("BTC/USDT", "ETH/USDT", "crypto", 30, 1.8, 0.35, 0.08, 48, 2.8, 0.80, 0.05),
    # India dormant until week 7+ (NSE module not live yet)
    Pair("HDFCBANK", "ICICIBANK", "india",  40, 1.7, 0.30, 0.05,  5, 2.8, 0.70, 0.05),
]


# == State management ==========================================================

# Unified positions ledger wiring (Q1-Q4=A, ledger commit 3/3 2026-05-21).
# Flag is read ONCE at module import per Q4=A; flips require container restart.
from foundation import state_bridge as _state_bridge

STRATEGY_ID = "C1_stat_arb"
MARKET = "crypto"
_USE_UNIFIED_LEDGER = _state_bridge.is_unified_ledger_enabled()


def _load_state() -> dict:
    if _USE_UNIFIED_LEDGER:
        return _state_bridge.load_state(STRATEGY_ID, MARKET, _STATE_FILE,
                                        use_unified=True)
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    if _USE_UNIFIED_LEDGER:
        _state_bridge.save_state(STRATEGY_ID, MARKET, state, _STATE_FILE,
                                 use_unified=True)
        return
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2))


# == Pair health cache (weekly Engle-Granger cadence) ==========================

def _load_pair_health() -> dict:
    """Load cached pair health checks. Returns {} if missing or corrupt."""
    if _HEALTH_FILE.exists():
        try:
            return json.loads(_HEALTH_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_pair_health(health: dict) -> None:
    """Persist pair health cache to disk."""
    _HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HEALTH_FILE.write_text(json.dumps(health, indent=2, default=str))


def _is_health_stale(health_entry: dict, max_age_days: int = 7) -> bool:
    """Return True if health entry is older than max_age_days."""
    checked_at = health_entry.get("checked_at")
    if not checked_at:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(checked_at)
        return age > timedelta(days=max_age_days)
    except Exception:
        return True


# == Statistical helpers ========================================================

def _engle_granger_pvalue(a: pd.Series, b: pd.Series) -> float:
    """
    Run Engle-Granger cointegration test on series a and b.
    Returns p-value (lower = stronger cointegration evidence).
    Falls back to 0.0 (always pass) if statsmodels is not installed.
    """
    try:
        from statsmodels.tsa.stattools import coint
        _, pvalue, _ = coint(a.dropna().values, b.dropna().values)
        return float(pvalue)
    except ImportError:
        log.warning("statsmodels not installed -- cointegration check bypassed (p=0.0 assumed)")
        return 0.0
    except Exception as exc:
        log.warning(f"Engle-Granger test failed: {exc} -- assuming p=0.0")
        return 0.0


def _rolling_correlation(a: pd.Series, b: pd.Series, n: int) -> float | None:
    """
    Pearson correlation of the last n bars of series a and b.

    Returns None on insufficient data or NaN so the caller can distinguish
    "I can't compute this yet" from a genuine ~0 correlation. Previously
    returned 0.0, which silently failed the health gate's `corr >= 0.80`
    check and poisoned the 7-day-cached pair_healthy=False state when
    fetch depth was below the requested window.
    """
    combined = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(combined) < n:
        return None
    corr = combined.tail(n)["a"].corr(combined.tail(n)["b"])
    if pd.isna(corr):
        return None
    return float(corr)


# == Spread computation =========================================================

def _compute_spread_zscore(
    prices_a: pd.Series, prices_b: pd.Series, window: int
) -> tuple[float, float]:
    """
    Compute log spread and its rolling z-score.

    spread = log(price_a) - log(price_b)
    z      = (spread_now - mean(spread[-window:])) / std(spread[-window:])

    Returns (spread, z_score).
    """
    if len(prices_a) < window + 5 or len(prices_b) < window + 5:
        return 0.0, 0.0

    combined = pd.DataFrame({"a": prices_a, "b": prices_b}).dropna()
    if len(combined) < window + 2:
        return 0.0, 0.0

    log_a  = np.log(combined["a"].clip(lower=1e-9))
    log_b  = np.log(combined["b"].clip(lower=1e-9))
    spread = log_a - log_b

    rolling_mean = spread.rolling(window).mean()
    rolling_std  = spread.rolling(window).std().clip(lower=1e-9)

    spread_now = float(spread.iloc[-1])
    mean_now   = float(rolling_mean.iloc[-1])
    std_now    = float(rolling_std.iloc[-1])

    z = (spread_now - mean_now) / std_now
    return spread_now, z


# == Execution helpers ==========================================================

def _record_stat_arb_trade(
    market: str, symbol: str, action: str, shares: float,
    price: float, pnl: float = 0.0, note: str = "",
    confidence: float = 0.0, exit_reason: str = "",
    entry_time: str | None = None, exit_time: str | None = None,
) -> None:
    """Write a stat-arb trade to the main paper_trades.db."""
    try:
        from execution.paper_trader import record_trade
        size_usd = round(shares * price, 4)
        pnl_pct  = round(pnl / size_usd * 100, 4) if size_usd and action == "SELL" else None
        notes_d  = {"confidence": confidence}
        if exit_reason:
            notes_d["exit_reason"] = exit_reason
        record_trade(
            db_path=_DB_PATH, market=market, symbol=symbol,
            action=action, shares=shares, price=price,
            signal="STAT_ARB", regime="PAIRS", risk_action="ALLOW",
            pnl=pnl if pnl != 0.0 else 0.0, note=note,
            strategy="C1_stat_arb",
            entry_time=entry_time, exit_time=exit_time,
            pnl_pct=pnl_pct, notes=notes_d, size_usd=size_usd,
        )
    except Exception as exc:
        log.warning(f"  stat_arb record_trade failed: {exc}")


def _send(msg: str, market: str) -> None:
    try:
        from observability.alerts import send_alert
        send_alert(msg, market=market)
    except Exception:
        pass


# == Close helper (shared by converge / hard-stop / time-stop exits) ===========

def _close_position(
    pair: Pair,
    key: str,
    z: float,
    price_a: float,
    price_b: float,
    position: dict,
    mkt_port: dict,
    state: dict,
    health: dict,
    reason: str = "CONVERGE",
) -> tuple[dict, dict]:
    """Unified exit logic for all three exit conditions."""
    side     = position["side"]
    shares_a = position["shares_a"]
    shares_b = position["shares_b"]
    entry_a  = position["entry_price_a"]
    entry_b  = position["entry_price_b"]
    entry_z  = position["entry_z"]

    if side == "LONG_A":
        pnl_a = (price_a - entry_a) * shares_a
        pnl_b = (entry_b - price_b) * shares_b
    else:
        pnl_a = (entry_a - price_a) * shares_a
        pnl_b = (price_b - entry_b) * shares_b

    total_pnl   = pnl_a + pnl_b
    entry_alloc = position.get("entry_alloc") or (shares_a * entry_a)

    mkt_port["capital"]      += entry_alloc * 2 + total_pnl
    mkt_port["realized_pnl"] += total_pnl
    mkt_port["total_trades"] += 2
    if total_pnl >= 0:
        mkt_port["wins"]   += 1
    else:
        mkt_port["losses"] += 1

    note = f"stat_arb EXIT {reason} {side} | z={z:.3f} | entry_z={entry_z:.3f}"
    _record_stat_arb_trade(pair.market, pair.long_sym, "SELL", shares_a, price_a, pnl=pnl_a, note=note)
    _record_stat_arb_trade(pair.market, pair.short_sym, "BUY",  shares_b, price_b, pnl=pnl_b, note=note)

    icon = "GREEN" if total_pnl >= 0 else "RED"
    log.info(
        f"  [{icon}] STAT_ARB EXIT {key} | reason={reason} "
        f"side={side} pnl={total_pnl:+.4f} z={z:.3f}"
    )
    _send(
        f"STAT_ARB EXIT {key} | {reason} | PnL={total_pnl:+.4f} | z={z:.2f}",
        pair.market,
    )

    state.pop(key, None)
    return state, health


# == Core pair runner ===========================================================

def _run_pair(
    pair: Pair,
    prices_a: pd.Series,
    prices_b: pd.Series,
    portfolio: dict,
    state: dict,
    health: dict,
    gate_check=None,
    full_positions: dict | None = None,
    full_portfolio: dict | None = None,
) -> tuple[dict, dict]:
    """
    Evaluate one pair: update health cache, check exits, check entry.

    Position encoding in state[key]:
        side, shares_a, shares_b, entry_price_a, entry_price_b,
        entry_z, entry_time, entry_alloc

    Kill-switch gate (B') wiring:
        gate_check, full_positions, full_portfolio are resolved by the
        public runner (run_stat_arb_crypto). When gate_check is None
        (test / back-compat callers), all entries and exits proceed
        ungated. When gate_check is set, it is consulted before any BUY
        or SELL emission; on HALT, the offending leg is skipped and
        re-evaluated next cycle. Parity with C3 (altcoin_reversion.py)
        and C6 (bollinger_range.py).
    """
    key      = f"{pair.long_sym}_{pair.short_sym}"
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
    alloc    = capital * pair.alloc_pct

    # -- HEALTH GATE: refresh weekly Engle-Granger + correlation cache --------
    health_entry = health.get(key, {})
    if _is_health_stale(health_entry):
        # crypto: 14 days * 24 hours; india: 14 daily bars
        n_corr = 14 * 24 if pair.market == "crypto" else 14
        corr14 = _rolling_correlation(prices_a, prices_b, n_corr)
        if corr14 is None:
            # Insufficient data — don't poison the cache. Existing health_entry
            # (possibly empty) remains; will retry on next cycle.
            window_days = n_corr // (24 if pair.market == "crypto" else 1)
            log.warning(
                f"  [{key}] health update SKIPPED: need {n_corr} bars for "
                f"{window_days}d correlation, have {len(prices_a)}. "
                f"Retry next cycle."
            )
        else:
            eg_p    = _engle_granger_pvalue(prices_a, prices_b)
            healthy = eg_p < pair.cointegration_p_max and corr14 >= pair.min_correlation_14d
            health[key] = {
                "eg_pvalue":    eg_p,
                "corr_14d":     corr14,
                "checked_at":   datetime.now(timezone.utc).isoformat(),
                "pair_healthy": healthy,
            }
            log.info(
                f"  [{key}] health updated: eg_p={eg_p:.4f} "
                f"corr14d={corr14:.3f} healthy={healthy}"
            )
            health_entry = health[key]

    pair_healthy  = health_entry.get("pair_healthy", True)
    cached_eg_p   = health_entry.get("eg_pvalue", 0.0)
    cached_corr14 = health_entry.get("corr_14d", 1.0)

    # -- Kill-switch gate (B'): close branch ---------------------------------
    # Block SELL/BUY emissions for any exit (CONVERGE / HARD_STOP / TIME_STOP)
    # before mutating state, capital, or persistence. If the gate trips, the
    # position stays open and is re-evaluated next cycle.
    def _exit_gate_ok() -> bool:
        if gate_check is None:
            return True
        _allowed, _kill_reason = gate_check(
            pair.market, pair.long_sym, price_a,
            full_positions, full_portfolio,
        )
        if not _allowed:
            log.info(f"[c1] {key}: SKIP EXIT — kill switch active ({_kill_reason})")
        return _allowed

    # -- EXIT: spread converged -----------------------------------------------
    if position and abs(z) < pair.exit_z:
        if not _exit_gate_ok():
            return state, health
        return _close_position(pair, key, z, price_a, price_b, position, mkt_port, state, health, reason="CONVERGE")

    # -- EXIT: hard stop (spread blowing out) ---------------------------------
    if position and abs(z) >= pair.hard_stop_z:
        log.warning(f"  HARD_STOP {key}: |z|={abs(z):.3f} >= {pair.hard_stop_z}")
        if not _exit_gate_ok():
            return state, health
        return _close_position(pair, key, z, price_a, price_b, position, mkt_port, state, health, reason="HARD_STOP")

    # -- EXIT: time stop (max hold exceeded) ----------------------------------
    if position:
        entry_time = datetime.fromisoformat(position["entry_time"])
        age_hours  = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
        if age_hours >= pair.time_stop_hours:
            log.warning(
                f"  TIME_STOP {key}: held {age_hours:.1f}H >= {pair.time_stop_hours}H"
            )
            if not _exit_gate_ok():
                return state, health
            return _close_position(pair, key, z, price_a, price_b, position, mkt_port, state, health, reason="TIME_STOP")

    # -- ENTRY: no position, spread stretched, health gate passes -------------
    if not position and abs(z) > pair.entry_z:
        if not pair_healthy:
            log.info(
                f"  SKIP ENTRY {key}: health gate failed "
                f"(eg_p={cached_eg_p:.4f} corr14d={cached_corr14:.3f})"
            )
            return state, health

        if alloc * 2 > capital:
            log.info(f"  Insufficient capital for stat_arb {key} -- skip")
            return state, health

        # Kill-switch gate (B') — block ENTRY emission BEFORE any state
        # mutation, DB write, or capital adjustment. Parity with C3/C6.
        if gate_check is not None:
            _allowed, _kill_reason = gate_check(
                pair.market, pair.long_sym, price_a,
                full_positions, full_portfolio,
            )
            if not _allowed:
                log.info(f"[c1] {key}: SKIP ENTRY — kill switch active ({_kill_reason})")
                return state, health

        shares_a = alloc / max(price_a, 1e-9)
        shares_b = alloc / max(price_b, 1e-9)
        side     = "SHORT_A" if z > 0 else "LONG_A"

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
            f"  STAT_ARB ENTRY {key} | side={side} z={z:.3f} "
            f"alloc={alloc:.2f}x2 | eg_p={cached_eg_p:.4f} corr14d={cached_corr14:.3f}"
        )
        _send(
            f"STAT_ARB ENTRY {key} | {side} | z={z:.2f} | alloc={alloc:.2f}x2",
            pair.market,
        )

    else:
        status = f"OPEN z={z:.3f}" if position else "no entry"
        log.debug(f"  [{key}] {status} -- no action")

    return state, health


# == Public runners =============================================================

def run_stat_arb_crypto(
    portfolio: dict,
    fetch_hourly_fn,
    full_positions: dict | None = None,
    full_portfolio: dict | None = None,
) -> None:
    """
    Run crypto pairs stat-arb. Call once per cycle from run_crypto().

    Args:
        portfolio:       The live portfolio dict (mutated in-place).
        fetch_hourly_fn: Callable(symbol) -> pd.DataFrame | None
        full_positions:  Full positions dict {"crypto": {...}, "india": {...}}.
                         Required for kill-switch gate (B' helper). When None
                         (test/back-compat callers), the gate is bypassed.
        full_portfolio:  Full portfolio dict, same role as full_positions.
    """
    _gate_check = None
    if full_positions is not None and full_portfolio is not None:
        try:
            from trading.live_paper_runner import apply_kill_switch_gate as _gate_check
        except Exception as exc:
            log.warning(f"[c1] kill-switch helper unavailable ({exc}) — proceeding ungated")
            _gate_check = None

    state        = _load_state()
    health       = _load_pair_health()
    crypto_pairs = [p for p in PAIRS if p.market == "crypto"]

    for pair in crypto_pairs:
        try:
            df_a = fetch_hourly_fn(pair.long_sym)
            df_b = fetch_hourly_fn(pair.short_sym)
            if df_a is None or df_b is None:
                log.debug(f"  No data for {pair.long_sym}/{pair.short_sym}")
                continue
            if len(df_a) < pair.window + 5 or len(df_b) < pair.window + 5:
                log.debug(f"  Insufficient bars for {pair.long_sym}/{pair.short_sym}")
                continue

            prices_a = df_a.set_index("timestamp")["close"] if "timestamp" in df_a.columns else df_a["close"]
            prices_b = df_b.set_index("timestamp")["close"] if "timestamp" in df_b.columns else df_b["close"]

            state, health = _run_pair(
                pair, prices_a, prices_b, portfolio, state, health,
                gate_check=_gate_check,
                full_positions=full_positions,
                full_portfolio=full_portfolio,
            )
        except Exception as exc:
            log.error(f"  Stat-arb crypto {pair.long_sym}/{pair.short_sym}: {exc}", exc_info=True)

    _save_state(state)
    _save_pair_health(health)


def run_stat_arb_india(
    portfolio: dict,
    fetch_hourly_fn,
) -> None:
    """
    Run NSE pairs stat-arb. Call once per cycle from run_india().

    Args:
        portfolio:       The live portfolio dict (mutated in-place).
        fetch_hourly_fn: Callable(symbol, token, exchange) -> pd.DataFrame | None
    """
    _TOKEN_MAP = {
        "HDFCBANK":  ("1333", "NSE"),
        "ICICIBANK": ("4963", "NSE"),
    }

    state       = _load_state()
    health      = _load_pair_health()
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

            if df_a is None or df_b is None:
                log.debug(f"  No data for {pair.long_sym}/{pair.short_sym}")
                continue
            if len(df_a) < pair.window + 5 or len(df_b) < pair.window + 5:
                log.debug(f"  Insufficient bars for {pair.long_sym}/{pair.short_sym}")
                continue

            prices_a = df_a["close"] if "close" in df_a.columns else df_a.iloc[:, 4]
            prices_b = df_b["close"] if "close" in df_b.columns else df_b.iloc[:, 4]

            state, health = _run_pair(pair, prices_a, prices_b, portfolio, state, health)
        except Exception as exc:
            log.error(f"  Stat-arb India {pair.long_sym}/{pair.short_sym}: {exc}", exc_info=True)

    _save_state(state)
    _save_pair_health(health)


# == Reporting ==================================================================

def get_open_stat_arb_positions() -> dict:
    """Return current open stat-arb positions for reporting."""
    return _load_state()


def get_stat_arb_summary(portfolio: dict) -> dict:
    """Return position count, unrealized P&L, and health metadata for dashboard."""
    state  = _load_state()
    health = _load_pair_health()
    summary = {
        "open_pairs":     len(state),
        "unrealized_pnl": 0.0,
        "positions":      [],
    }
    for key, pos in state.items():
        h = health.get(key, {})
        summary["positions"].append({
            "pair":       key,
            "side":       pos.get("side"),
            "entry_z":    pos.get("entry_z"),
            "entry_time": pos.get("entry_time"),
            "eg_pvalue":  h.get("eg_pvalue"),
            "corr_14d":   h.get("corr_14d"),
            "pair_healthy": h.get("pair_healthy"),
        })
    return summary
