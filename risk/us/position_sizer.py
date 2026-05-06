"""
Position sizer for US equities.

Implements Quarter-Kelly + ATR-based position sizing.
Pure computation module — zero network calls, zero DB calls, zero file I/O.

Quarter-Kelly formula:
    kelly_f = win_rate - (1 - win_rate) / edge_ratio
    scaled by 1/KELLY_DIVISOR, then capped at MAX_RISK_PCT of portfolio value.

Stop distance is ATR-based: stop_distance = atr_multiplier × atr_14
"""

import math
from dataclasses import dataclass

import numpy as np  # scipy dependency — isfinite() guards on Kelly intermediate values

from foundation.logger import get_logger

# ── Named constants ────────────────────────────────────────────────────────────
MAX_RISK_PCT = 0.015  # 1.5% max risk per trade
MAX_POSITION_PCT = 0.10  # 10% max concentration per position
KELLY_DIVISOR = 4  # Quarter-Kelly safety scaling
DEFAULT_WIN_RATE = 0.52
DEFAULT_EDGE_RATIO = 1.5
DEFAULT_ATR_MULTIPLIER = 2.0

log = get_logger(market="us", module="position_sizer")


@dataclass
class SizingInput:
    """All inputs required to compute one position size."""

    symbol: str
    entry_price: float  # Signal entry price (USD)
    atr_14: float  # ATR(14) at signal time — from feature store
    portfolio_value: float  # Total US portfolio allocation (USD)
    win_rate: float = DEFAULT_WIN_RATE  # Strategy win rate estimate (0.0–1.0)
    edge_ratio: float = DEFAULT_EDGE_RATIO  # avg_win / avg_loss ratio
    atr_multiplier: float = (
        DEFAULT_ATR_MULTIPLIER  # stop distance = atr_multiplier × ATR
    )


@dataclass
class SizingOutput:
    """Result of one position sizing computation."""

    symbol: str
    shares: int  # Always integer — no fractional shares
    entry_price: float
    stop_price: float  # entry_price - (atr_multiplier × atr_14) for long
    risk_per_share: float  # entry_price - stop_price
    total_risk_usd: float  # shares × risk_per_share
    position_value_usd: float  # shares × entry_price
    risk_pct_of_portfolio: float  # total_risk_usd / portfolio_value
    position_pct_of_portfolio: float  # position_value_usd / portfolio_value
    approved: bool
    rejection_reason: str | None  # None if approved


def _build_output(
    inp: SizingInput,
    shares: int,
    stop_price: float,
    risk_per_share: float,
    approved: bool,
    rejection_reason: str | None,
) -> SizingOutput:
    """Compute derived fields and assemble a SizingOutput."""
    position_value_usd = shares * inp.entry_price
    total_risk_usd = shares * risk_per_share
    risk_pct = total_risk_usd / inp.portfolio_value if inp.portfolio_value > 0 else 0.0
    position_pct = (
        position_value_usd / inp.portfolio_value if inp.portfolio_value > 0 else 0.0
    )

    if not approved:
        log.warning(
            "Position rejected",
            symbol=inp.symbol,
            rejection_reason=rejection_reason,
        )

    return SizingOutput(
        symbol=inp.symbol,
        shares=shares,
        entry_price=inp.entry_price,
        stop_price=stop_price,
        risk_per_share=risk_per_share,
        total_risk_usd=total_risk_usd,
        position_value_usd=position_value_usd,
        risk_pct_of_portfolio=risk_pct,
        position_pct_of_portfolio=position_pct,
        approved=approved,
        rejection_reason=rejection_reason,
    )


def size_position(inp: SizingInput) -> SizingOutput:
    """
    Compute a Quarter-Kelly ATR-based position size for a US equity trade.

    Algorithm:
        1. Validate all inputs — return rejected output immediately on any failure.
        2. Compute Kelly fraction: kelly_f = win_rate - (1 - win_rate) / edge_ratio.
        3. Hard-reject non-positive Kelly — a strategy with no edge gets zero capital.
        4. Scale to quarter-Kelly, cap at MAX_RISK_PCT, floor shares to integer.
        5. Apply concentration and minimum-share guards.

    Args:
        inp: SizingInput with all required trade parameters.

    Returns:
        SizingOutput. Always check .approved before acting on .shares.
        All error conditions produce approved=False with rejection_reason set;
        this function never raises.
    """
    log.info(
        "Computing position size",
        symbol=inp.symbol,
        entry_price=inp.entry_price,
        atr_14=inp.atr_14,
        portfolio_value=inp.portfolio_value,
        win_rate=inp.win_rate,
        edge_ratio=inp.edge_ratio,
    )

    # ── Input validation ──────────────────────────────────────────────────────
    if inp.entry_price <= 0:
        return _build_output(
            inp, 0, 0.0, 0.0, False, "Invalid entry price: must be > 0"
        )

    if inp.atr_14 <= 0:
        return _build_output(inp, 0, 0.0, 0.0, False, "Invalid ATR: must be > 0")

    if inp.portfolio_value <= 0:
        return _build_output(
            inp, 0, 0.0, 0.0, False, "Invalid portfolio value: must be > 0"
        )

    if not (0 < inp.win_rate < 1):
        return _build_output(
            inp, 0, 0.0, 0.0, False, "Win rate must be between 0 and 1"
        )

    # ── Step 1–2: Kelly fraction ──────────────────────────────────────────────
    kelly_f = inp.win_rate - (1.0 - inp.win_rate) / inp.edge_ratio

    # Guard against NaN/inf from extreme edge_ratio or win_rate values
    if not np.isfinite(kelly_f) or kelly_f <= 0:
        return _build_output(
            inp,
            0,
            0.0,
            0.0,
            False,
            "Negative Kelly: strategy has no edge at these parameters",
        )

    # ── Step 3: Risk USD — quarter-Kelly, capped at MAX_RISK_PCT ─────────────
    quarter_kelly_f = kelly_f / KELLY_DIVISOR
    kelly_risk_usd = quarter_kelly_f * inp.portfolio_value
    max_risk_usd = MAX_RISK_PCT * inp.portfolio_value
    risk_usd = min(kelly_risk_usd, max_risk_usd)

    # ── Step 4: Stop distance and stop price ─────────────────────────────────
    stop_distance = inp.atr_multiplier * inp.atr_14
    stop_price = inp.entry_price - stop_distance

    if stop_distance <= 0:
        return _build_output(
            inp,
            0,
            stop_price,
            0.0,
            False,
            "Stop distance is zero — division by zero risk",
        )

    if stop_price <= 0:
        return _build_output(
            inp,
            0,
            stop_price,
            stop_distance,
            False,
            "Stop price is zero or negative — ATR too large relative to entry price",
        )

    # ── Step 5: Shares — always floor, never round up ────────────────────────
    risk_per_share = stop_distance
    raw_shares = risk_usd / risk_per_share
    shares = math.floor(raw_shares)

    # ── Step 6–7: Position metrics ────────────────────────────────────────────
    position_value_usd = shares * inp.entry_price
    total_risk_usd = shares * risk_per_share
    risk_pct_of_portfolio = total_risk_usd / inp.portfolio_value
    position_pct_of_portfolio = position_value_usd / inp.portfolio_value

    # ── Validation rules ─────────────────────────────────────────────────────
    if shares < 1:
        return _build_output(
            inp,
            shares,
            stop_price,
            risk_per_share,
            False,
            "Position too small: 0 shares computed",
        )

    if risk_pct_of_portfolio > MAX_RISK_PCT:
        reason = f"Risk {risk_pct_of_portfolio:.2%} exceeds 1.5% max"
        return _build_output(inp, shares, stop_price, risk_per_share, False, reason)

    if position_pct_of_portfolio > MAX_POSITION_PCT:
        reason = (
            f"Position {position_pct_of_portfolio:.2%} exceeds 10% concentration limit"
        )
        return _build_output(inp, shares, stop_price, risk_per_share, False, reason)

    log.info(
        "Position approved",
        symbol=inp.symbol,
        shares=shares,
        stop_price=stop_price,
        risk_pct=f"{risk_pct_of_portfolio:.2%}",
        position_pct=f"{position_pct_of_portfolio:.2%}",
    )

    return SizingOutput(
        symbol=inp.symbol,
        shares=shares,
        entry_price=inp.entry_price,
        stop_price=stop_price,
        risk_per_share=risk_per_share,
        total_risk_usd=total_risk_usd,
        position_value_usd=position_value_usd,
        risk_pct_of_portfolio=risk_pct_of_portfolio,
        position_pct_of_portfolio=position_pct_of_portfolio,
        approved=True,
        rejection_reason=None,
    )
