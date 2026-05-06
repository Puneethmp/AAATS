"""
Tests for risk/us/position_sizer.py.

Pure computation — no mocks, no fixtures, no I/O.
All tests verify mathematical correctness of Quarter-Kelly + ATR sizing.

Spec note (FLAGGED_ISSUES.md): the original test_normal_sizing description specifies
ATR=2.0, price=100, portfolio=100000 → approved=True. However, those parameters
produce position_pct=37.5% which exceeds the 10% concentration limit and would be
rejected. Tests below use ATR=10.0 (position_pct=7.5%) to achieve the intended
approved=True outcome.
"""

import math

from risk.us.position_sizer import (
    MAX_POSITION_PCT,
    MAX_RISK_PCT,
    SizingInput,
    SizingOutput,
    size_position,
)

# ── Test 1: Normal sizing ─────────────────────────────────────────────────────


def test_normal_sizing():
    """Standard parameters produce an approved position within all limits.

    Computation:
        kelly_f = 0.55 - 0.45/1.5 = 0.25  →  quarter_kelly_f = 0.0625
        kelly_risk_usd = 6250  →  capped at max_risk_usd = 1500
        risk_per_share = 2.0 * 10.0 = 20.0
        raw_shares = 1500 / 20.0 = 75  →  shares = 75
        position_value = 75 * 100 = 7500  →  position_pct = 7.5% < 10% ✓
        risk_pct = 1500 / 100000 = 1.5% ✓
    """
    inp = SizingInput(
        symbol="AAPL",
        entry_price=100.0,
        atr_14=10.0,
        portfolio_value=100_000.0,
        win_rate=0.55,
        edge_ratio=1.5,
        atr_multiplier=2.0,
    )
    out = size_position(inp)

    assert out.approved is True
    assert out.shares > 0
    assert out.risk_pct_of_portfolio <= MAX_RISK_PCT
    assert out.position_pct_of_portfolio <= MAX_POSITION_PCT
    assert isinstance(out, SizingOutput)


# ── Test 2: Max risk cap ──────────────────────────────────────────────────────


def test_max_risk_cap():
    """Kelly output well above 1.5% is capped at MAX_RISK_PCT; still approved.

    Computation:
        kelly_f = 0.70 - 0.30/3.0 = 0.60  →  kelly_risk = 15% of portfolio
        Capped at max_risk_usd = 1500 (1.5%)
        risk_per_share = 20.0, raw_shares = 75, position_pct = 7.5% < 10% ✓
    """
    inp = SizingInput(
        symbol="MSFT",
        entry_price=100.0,
        atr_14=10.0,
        portfolio_value=100_000.0,
        win_rate=0.70,
        edge_ratio=3.0,
        atr_multiplier=2.0,
    )
    out = size_position(inp)

    assert out.approved is True
    assert out.risk_pct_of_portfolio <= MAX_RISK_PCT
    assert out.shares > 0


# ── Test 3: Concentration limit ───────────────────────────────────────────────


def test_concentration_limit():
    """High-price stock with tight ATR → position exceeds 10% → rejected.

    Computation:
        risk_per_share = 2.0 * 0.5 = 1.0
        max_risk_usd = 1500  →  raw_shares = 1500
        position_value = 1500 * 200 = $300k  →  position_pct = 300% > 10%  →  rejected
    """
    inp = SizingInput(
        symbol="BRK",
        entry_price=200.0,
        atr_14=0.5,
        portfolio_value=100_000.0,
        win_rate=0.55,
        edge_ratio=1.5,
        atr_multiplier=2.0,
    )
    out = size_position(inp)

    assert out.approved is False
    assert out.rejection_reason is not None
    assert "concentration" in out.rejection_reason.lower()


# ── Test 4: Zero shares ───────────────────────────────────────────────────────


def test_zero_shares():
    """Tiny portfolio + high-price stock + wide ATR → 0 shares → rejected.

    Computation:
        max_risk_usd = 0.015 * 5000 = 75
        risk_per_share = 2.0 * 100.0 = 200.0
        raw_shares = 75 / 200 = 0.375  →  floor = 0  →  rejected
    """
    inp = SizingInput(
        symbol="GOOGL",
        entry_price=10_000.0,
        atr_14=100.0,
        portfolio_value=5_000.0,
        win_rate=0.55,
        edge_ratio=1.5,
        atr_multiplier=2.0,
    )
    out = size_position(inp)

    assert out.approved is False
    assert out.rejection_reason is not None
    assert "too small" in out.rejection_reason.lower()
    assert out.shares == 0


# ── Test 5: Negative Kelly ────────────────────────────────────────────────────


def test_negative_kelly():
    """Win rate 30% with edge_ratio 1.0 gives negative Kelly → hard stop.

    Computation:
        kelly_f = 0.30 - 0.70/1.0 = -0.40 < 0  →  rejected immediately
        No capital allocated to a strategy with no mathematical edge.
    """
    inp = SizingInput(
        symbol="JUNK",
        entry_price=100.0,
        atr_14=2.0,
        portfolio_value=100_000.0,
        win_rate=0.30,
        edge_ratio=1.0,
        atr_multiplier=2.0,
    )
    out = size_position(inp)

    assert out.approved is False
    assert out.rejection_reason is not None
    assert "Negative Kelly" in out.rejection_reason


# ── Test 6: Invalid ATR ───────────────────────────────────────────────────────


def test_invalid_atr():
    """ATR=0 is invalid and caught before any computation."""
    inp = SizingInput(
        symbol="AAPL",
        entry_price=100.0,
        atr_14=0.0,
        portfolio_value=100_000.0,
    )
    out = size_position(inp)

    assert out.approved is False
    assert out.rejection_reason is not None
    assert "Invalid ATR" in out.rejection_reason


# ── Test 7: Stop price calculation ───────────────────────────────────────────


def test_stop_price_calculation():
    """stop_price = entry_price - (atr_multiplier × atr_14) to 4 decimal places.

    Computation:
        stop_distance = 2.0 * 5.1234 = 10.2468
        stop_price = 50.0 - 10.2468 = 39.7532
        position check: raw_shares ≈ 146, position_value=7300, pct=7.3% < 10% ✓
    """
    atr_14 = 5.1234
    entry_price = 50.0
    atr_multiplier = 2.0

    inp = SizingInput(
        symbol="AAPL",
        entry_price=entry_price,
        atr_14=atr_14,
        portfolio_value=100_000.0,
        win_rate=0.55,
        edge_ratio=1.5,
        atr_multiplier=atr_multiplier,
    )
    out = size_position(inp)

    expected_stop = entry_price - atr_multiplier * atr_14
    assert round(out.stop_price, 4) == round(expected_stop, 4)
    assert out.approved is True


# ── Test 8: Shares always floor ──────────────────────────────────────────────


def test_shares_floor():
    """raw_shares=10.9 → shares=10, never 11.

    Computation:
        risk_per_share = 2.0 * 68.805 = 137.61
        max_risk_usd = 0.015 * 100000 = 1500
        raw_shares = 1500 / 137.61 ≈ 10.901  →  floor = 10, not round-up to 11
        position_value = 10 * 500 = 5000  →  position_pct = 5% < 10% ✓
    """
    inp = SizingInput(
        symbol="TSLA",
        entry_price=500.0,
        atr_14=68.805,
        portfolio_value=100_000.0,
        win_rate=0.55,
        edge_ratio=1.5,
        atr_multiplier=2.0,
    )
    out = size_position(inp)

    assert out.shares == 10
    assert out.approved is True
    # Confirm floor — raw_shares was above 10 but below 11
    risk_per_share = 2.0 * 68.805
    max_risk_usd = MAX_RISK_PCT * 100_000.0
    raw_shares = max_risk_usd / risk_per_share
    assert 10 < raw_shares < 11
    assert math.floor(raw_shares) == 10
