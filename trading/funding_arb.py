"""
trading/funding_arb.py  —  C5b Funding Rate Arbitrage (Delta-Neutral)

Strategy:
  - Long spot BTC/ETH + Short perpetual BTC/ETH simultaneously (delta-neutral)
  - Collect positive funding payments when perpetual funding rate > threshold
  - Exit when funding rate drops or position exceeds max hold age

Capital: CAPITAL_PER_SYMBOL = $25 per leg ($50 total per symbol, 2 symbols max = $100)
Entry:   funding_rate >= ENTRY_RATE_THRESHOLD (0.08%/8H)
Exit:    funding_rate <  EXIT_RATE_THRESHOLD  (0.02%/8H)  OR  age > MAX_HOLD_DAYS

Integrates with: live_paper_runner.py  →  run_funding_arb_crypto(portfolio)
Depends on:      risk/funding_monitor.py  (FundingMonitor for rate fetching)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
import pathlib
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

ENTRY_RATE_THRESHOLD = 0.0008   # 0.08% per 8H  — enter above this
_ROOT    = pathlib.Path(__file__).resolve().parents[1]
_DB_PATH = str(_ROOT / "data" / "paper_trades.db")
EXIT_RATE_THRESHOLD  = 0.0002   # 0.02% per 8H  — exit below this
CAPITAL_PER_SYMBOL   = 25.0     # USD per leg (spot leg + perp leg = $50 total)
MAX_HOLD_DAYS        = 14       # Hard cap: exit after 14 days regardless
PAYMENTS_PER_DAY     = 3        # 3 funding settlements per day (every 8H)
STATE_FILE           = Path("data/funding_arb_state.json")

# (spot_symbol, perp_symbol, base_asset)
SYMBOLS = [
    ("BTC/USDT", "BTC/USDT:USDT", "BTC"),
    ("ETH/USDT", "ETH/USDT:USDT", "ETH"),
]

# ─── State I/O ────────────────────────────────────────────────────────────────

def _load_state() -> dict[str, Any]:
    """Load persisted position state from JSON; return empty dict on first run."""
    if not STATE_FILE.exists():
        return {}
    try:
        raw = STATE_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning(f"[funding_arb] state file unreadable ({exc}), starting fresh")
        return {}


def _save_state(state: dict[str, Any]) -> None:
    """Persist position state atomically."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


# ─── Funding rate fetching ─────────────────────────────────────────────────────

def _fetch_funding_rate(perp_symbol: str) -> float | None:
    """
    Fetch current 8H funding rate for a perpetual symbol via FundingMonitor.
    Returns None on any error (treat as unavailable, skip this symbol).
    """
    try:
        from risk.funding_monitor import FundingMonitor
        monitor = FundingMonitor()
        rates = monitor.check_funding_rates([perp_symbol])
        # FundingMonitor returns dict keyed by symbol or base asset — try both
        if perp_symbol in rates:
            return float(rates[perp_symbol])
        # Try base asset key (BTC, ETH)
        for key, val in rates.items():
            if isinstance(key, str) and perp_symbol.split("/")[0] in key.upper():
                return float(val)
        log.debug(f"[funding_arb] {perp_symbol} not found in rate dict keys={list(rates)[:6]}")
        return None
    except Exception as exc:
        log.warning(f"[funding_arb] rate fetch failed for {perp_symbol}: {exc}")
        return None


# ─── Position helpers ─────────────────────────────────────────────────────────

def _age_days(entry_ts: str) -> float:
    """Return fractional days since entry_ts (ISO-8601 string)."""
    try:
        entry_dt = datetime.fromisoformat(entry_ts)
        now_dt = datetime.now(timezone.utc)
        return (now_dt - entry_dt).total_seconds() / 86400.0
    except Exception:
        return 0.0


def _accrued_income(position: dict[str, Any], current_rate: float) -> float:
    """
    Estimate income since last_accrual_ts using current funding rate.
    Income = capital_per_leg * funding_rate * payments_elapsed
    (Approximates continuous accrual; actual payments land every 8H.)
    """
    last_ts = position.get("last_accrual_ts", position["entry_ts"])
    try:
        last_dt = datetime.fromisoformat(last_ts)
        now_dt  = datetime.now(timezone.utc)
        hours_elapsed = (now_dt - last_dt).total_seconds() / 3600.0
        payments = hours_elapsed / 8.0   # fractional payments elapsed
    except Exception:
        payments = 0.0

    if payments <= 0:
        return 0.0

    capital_leg = position.get("capital_per_leg", CAPITAL_PER_SYMBOL)
    return capital_leg * current_rate * payments


def _open_position(base: str, entry_rate: float, portfolio: dict) -> dict | None:
    """
    Paper-open a delta-neutral funding arb position.
    Debits 2 × CAPITAL_PER_SYMBOL from portfolio capital.
    Returns position dict or None if insufficient capital.
    """
    required = CAPITAL_PER_SYMBOL * 2
    current_capital = portfolio.get("capital", 0.0)
    if current_capital < required:
        log.info(f"[funding_arb] {base}: insufficient capital "
                 f"(need ${required:.2f}, have ${current_capital:.2f}) — skip")
        return None

    portfolio["capital"] = current_capital - required
    now = datetime.now(timezone.utc).isoformat()
    pos = {
        "base":             base,
        "entry_rate":       entry_rate,
        "entry_ts":         now,
        "last_accrual_ts":  now,
        "capital_per_leg":  CAPITAL_PER_SYMBOL,
        "total_income":     0.0,
    }
    log.info(f"[funding_arb] OPEN  {base}  rate={entry_rate:.4%}  "
             f"capital_used=${required:.2f}  portfolio_remaining=${portfolio['capital']:.2f}")
    # Record BUY leg to paper_trades.db so Grafana metrics can see it
    try:
        from execution.paper_trader import record_trade as _rt
        _rt(
            db_path=_DB_PATH, market="crypto",
            symbol=f"{base}/USDT", action="BUY",
            shares=CAPITAL_PER_SYMBOL / 1.0,   # 1.0 placeholder price — delta-neutral notional
            price=1.0, signal="FUNDING_ARB",
            regime="NEUTRAL", risk_action="ALLOW",
            strategy="C5b_funding_arb",
            entry_time=now, size_usd=round(required, 4),
            notes={"entry_rate": entry_rate, "confidence": 1.0,
                   "exit_reason": "", "position_type": "delta_neutral"},
        )
    except Exception as _exc:
        log.debug(f"[funding_arb] record open failed: {_exc}")
    return pos


def _close_position(base: str, position: dict, reason: str, portfolio: dict) -> None:
    """
    Paper-close position: return capital + accrued income to portfolio.
    """
    returned = position["capital_per_leg"] * 2 + position.get("total_income", 0.0)
    portfolio["capital"] = portfolio.get("capital", 0.0) + returned
    income   = position.get("total_income", 0.0)
    log.info(f"[funding_arb] CLOSE {base}  reason={reason}  "
             f"income=${income:.4f}  "
             f"returned=${returned:.2f}  portfolio=${portfolio['capital']:.2f}")
    # Record SELL leg so Grafana has full round-trip visibility
    try:
        from execution.paper_trader import record_trade as _rt
        size_usd = position["capital_per_leg"] * 2
        pnl_pct  = round(income / size_usd * 100, 4) if size_usd else None
        _rt(
            db_path=_DB_PATH, market="crypto",
            symbol=f"{base}/USDT", action="SELL",
            shares=size_usd / 1.0, price=1.0,
            signal="FUNDING_ARB", regime="NEUTRAL", risk_action="ALLOW",
            pnl=income,
            strategy="C5b_funding_arb",
            entry_time=position.get("entry_ts"),
            exit_time=datetime.now(timezone.utc).isoformat(),
            pnl_pct=pnl_pct, size_usd=round(size_usd, 4),
            notes={"exit_reason": reason, "income_usd": income,
                   "confidence": 1.0, "position_type": "delta_neutral"},
        )
    except Exception as _exc:
        log.debug(f"[funding_arb] record close failed: {_exc}")


# ─── Public runner ─────────────────────────────────────────────────────────────

def run_funding_arb_crypto(portfolio: dict) -> None:
    """
    Main entry point called from live_paper_runner.py each cycle.

    For each tracked symbol:
      1. Fetch current 8H funding rate
      2. If position open:
         a. Accrue income since last_accrual_ts
         b. Exit if rate < EXIT_RATE_THRESHOLD or age > MAX_HOLD_DAYS
      3. If no position:
         a. Enter if rate >= ENTRY_RATE_THRESHOLD and capital available

    Modifies portfolio dict in-place (capital field).
    """
    state = _load_state()
    changed = False

    for spot_sym, perp_sym, base in SYMBOLS:
        rate = _fetch_funding_rate(perp_sym)
        if rate is None:
            log.debug(f"[funding_arb] {base}: rate unavailable this cycle")
            continue

        pos = state.get(base)

        if pos is not None:
            # ── Active position: accrue income ────────────────────────────────
            income = _accrued_income(pos, rate)
            if income > 0:
                pos["total_income"] = pos.get("total_income", 0.0) + income
                pos["last_accrual_ts"] = datetime.now(timezone.utc).isoformat()
                log.debug(f"[funding_arb] {base}: +${income:.4f} accrued  "
                          f"total=${pos['total_income']:.4f}")
                changed = True

            # ── Check exit conditions ─────────────────────────────────────────
            age = _age_days(pos["entry_ts"])
            if rate < EXIT_RATE_THRESHOLD:
                reason = f"rate_dropped({rate:.4%}<{EXIT_RATE_THRESHOLD:.4%})"
                _close_position(base, pos, reason, portfolio)
                del state[base]
                changed = True
            elif age > MAX_HOLD_DAYS:
                reason = f"max_age({age:.1f}d>{MAX_HOLD_DAYS}d)"
                _close_position(base, pos, reason, portfolio)
                del state[base]
                changed = True
            else:
                state[base] = pos  # update accrual timestamp
                log.info(f"[funding_arb] HOLD  {base}  "
                         f"rate={rate:.4%}  age={age:.1f}d  "
                         f"income=${pos['total_income']:.4f}")

        else:
            # ── No position: check entry ──────────────────────────────────────
            if rate >= ENTRY_RATE_THRESHOLD:
                new_pos = _open_position(base, rate, portfolio)
                if new_pos is not None:
                    state[base] = new_pos
                    changed = True
            else:
                log.debug(f"[funding_arb] {base}: rate={rate:.4%} below entry threshold — wait")

    if changed:
        _save_state(state)
