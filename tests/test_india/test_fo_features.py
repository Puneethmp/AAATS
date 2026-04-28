"""
Tests for markets/india/fo_feature_engineer.py.
No network calls — all computations use in-memory synthetic data.

Covers all 8 spec-required tests:
1. compute_pcr returns correct ratio
2. compute_pcr returns NaN (not ZeroDivisionError) when Call OI = 0
3. compute_iv_rank returns 50.0 when max == min
4. compute_iv_rank returns correct value for known inputs
5. compute_max_pain returns a strike that exists in the chain
6. compute_greeks: CE delta in [0, 1]
7. compute_greeks: PE delta in [-1, 0]
8. compute_greeks: theta is negative (time decay for ATM/OTM)
"""

import math

import pandas as pd
import pytest

from markets.india.fo_feature_engineer import (
    compute_greeks,
    compute_iv_rank,
    compute_max_pain,
    compute_pcr,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_chain(
    strikes: list[float],
    call_oi: list[float],
    put_oi: list[float],
    iv: float = 0.20,
) -> pd.DataFrame:
    """Build a minimal synthetic option chain DataFrame."""
    rows = []
    for s, c_oi, p_oi in zip(strikes, call_oi, put_oi):
        rows.append(
            {
                "strike": s,
                "option_type": "CE",
                "oi": c_oi,
                "iv": iv,
                "ltp": 0.0,
                "bid": 0.0,
                "ask": 0.0,
                "volume": 100,
                "change_in_oi": 0,
            }
        )
        rows.append(
            {
                "strike": s,
                "option_type": "PE",
                "oi": p_oi,
                "iv": iv,
                "ltp": 0.0,
                "bid": 0.0,
                "ask": 0.0,
                "volume": 100,
                "change_in_oi": 0,
            }
        )
    return pd.DataFrame(rows)


# Standard 3-strike chain used across multiple tests
_STRIKES = [18000.0, 18100.0, 18200.0]
_CALL_OI = [10_000.0, 8_000.0, 6_000.0]  # total = 24,000
_PUT_OI = [5_000.0, 7_000.0, 12_000.0]  # total = 24,000 → PCR = 1.0


# ── Tests: compute_pcr ────────────────────────────────────────────────────────


class TestComputePCR:
    def test_correct_ratio(self):
        """PCR = sum(put OI) / sum(call OI) for a balanced chain."""
        df = _make_chain(_STRIKES, _CALL_OI, _PUT_OI)
        result = compute_pcr(df)
        expected = sum(_PUT_OI) / sum(_CALL_OI)
        assert abs(result - expected) < 1e-9, f"Expected {expected}, got {result}"

    def test_returns_nan_not_zero_division_when_no_calls(self):
        """PCR must return float('nan') when Call OI sums to zero — not raise."""
        df = _make_chain([18000.0], call_oi=[0.0], put_oi=[5000.0])
        result = compute_pcr(df)
        assert math.isnan(result), f"Expected NaN, got {result}"

    def test_missing_column_raises(self):
        """Passing a DataFrame without 'oi' must raise ValueError."""
        bad = pd.DataFrame({"strike": [18000], "option_type": ["CE"]})
        with pytest.raises(ValueError, match="missing required columns"):
            compute_pcr(bad)


# ── Tests: compute_iv_rank ────────────────────────────────────────────────────


class TestComputeIVRank:
    def test_returns_50_when_flat_range(self):
        """IV Rank must be 50.0 when max_52w == min_52w (flat volatility history)."""
        result = compute_iv_rank(current_iv=20.0, iv_history_52w=[20.0, 20.0, 20.0])
        assert result == 50.0, f"Expected 50.0, got {result}"

    def test_returns_50_for_empty_history(self):
        """IV Rank must be 50.0 (neutral) for empty history — no crash."""
        result = compute_iv_rank(current_iv=25.0, iv_history_52w=[])
        assert result == 50.0, f"Expected 50.0 for empty history, got {result}"

    def test_correct_value_for_known_inputs(self):
        """Known input: current=30, history=[10, 40] → rank = (30-10)/(40-10)*100 = 66.67."""
        result = compute_iv_rank(current_iv=30.0, iv_history_52w=[10.0, 40.0])
        expected = (30.0 - 10.0) / (40.0 - 10.0) * 100.0
        assert (
            abs(result - expected) < 1e-9
        ), f"Expected {expected:.4f}, got {result:.4f}"

    def test_clamped_at_100_when_above_52w_max(self):
        """IV above the 52-week max must clamp to 100.0, not exceed it."""
        result = compute_iv_rank(current_iv=60.0, iv_history_52w=[10.0, 40.0])
        assert result == 100.0, f"Expected 100.0 (clamped), got {result}"

    def test_clamped_at_0_when_below_52w_min(self):
        """IV below the 52-week min must clamp to 0.0, not go negative."""
        result = compute_iv_rank(current_iv=5.0, iv_history_52w=[10.0, 40.0])
        assert result == 0.0, f"Expected 0.0 (clamped), got {result}"


# ── Tests: compute_max_pain ───────────────────────────────────────────────────


class TestComputeMaxPain:
    def test_returns_strike_that_exists_in_chain(self):
        """Max pain result must be one of the strikes in the option chain."""
        df = _make_chain(_STRIKES, _CALL_OI, _PUT_OI)
        result = compute_max_pain(df)
        assert result in _STRIKES, f"Max pain {result} not in strikes {_STRIKES}"

    def test_correct_max_pain_value(self):
        """
        Asymmetric chain: heavy call OI at high strikes → max pain biased toward lower strike.

        Setup:
          Strike 18000: CE OI=50000, PE OI=1000
          Strike 18200: CE OI=1000,  PE OI=50000

        At expiry=18000: call writers lose nothing, put writers lose (18000-18000)*50000=0
          → total = 0
        At expiry=18200: call writers lose (18200-18000)*50000=10M, put writers lose 0
          → total = 10M

        Max pain = 18000 (lower total loss).
        """
        strikes = [18000.0, 18200.0]
        call_oi = [50_000.0, 1_000.0]
        put_oi = [1_000.0, 50_000.0]
        df = _make_chain(strikes, call_oi, put_oi)
        result = compute_max_pain(df)
        assert result == 18000.0, f"Expected max pain at 18000, got {result}"

    def test_empty_strikes_raises(self):
        """An option chain with no rows must raise ValueError — not return NaN."""
        empty = pd.DataFrame(columns=["strike", "option_type", "oi"])
        with pytest.raises(ValueError, match="no strikes"):
            compute_max_pain(empty)


# ── Tests: compute_greeks ─────────────────────────────────────────────────────


# ATM parameters: spot=strike=18000, 30 days to expiry, 6.5% risk-free, 20% IV
_ATM_KWARGS = dict(
    underlying_price=18000.0,
    strike=18000.0,
    time_to_expiry_days=30.0,
    risk_free_rate=0.065,
    implied_volatility=0.20,
)


class TestComputeGreeks:
    def test_ce_delta_in_zero_to_one(self):
        """CE (call) delta must be in [0, 1]. ATM call delta ≈ 0.5."""
        result = compute_greeks(option_type="CE", **_ATM_KWARGS)
        assert (
            0.0 <= result["delta"] <= 1.0
        ), f"CE delta out of range: {result['delta']}"

    def test_pe_delta_in_minus_one_to_zero(self):
        """PE (put) delta must be in [-1, 0]. ATM put delta ≈ -0.5."""
        result = compute_greeks(option_type="PE", **_ATM_KWARGS)
        assert (
            -1.0 <= result["delta"] <= 0.0
        ), f"PE delta out of range: {result['delta']}"

    def test_theta_is_negative_for_atm_option(self):
        """Theta (daily decay) must be negative for ATM call and put."""
        ce = compute_greeks(option_type="CE", **_ATM_KWARGS)
        pe = compute_greeks(option_type="PE", **_ATM_KWARGS)
        assert ce["theta"] < 0.0, f"CE theta should be negative, got {ce['theta']}"
        assert pe["theta"] < 0.0, f"PE theta should be negative, got {pe['theta']}"

    def test_output_keys_present(self):
        """Result dict must contain exactly: delta, gamma, theta, vega."""
        result = compute_greeks(option_type="CE", **_ATM_KWARGS)
        assert set(result.keys()) == {"delta", "gamma", "theta", "vega"}

    def test_gamma_is_positive(self):
        """Gamma is always positive (option value is convex in underlying price)."""
        result = compute_greeks(option_type="CE", **_ATM_KWARGS)
        assert result["gamma"] > 0.0, f"Gamma must be positive, got {result['gamma']}"

    def test_ce_pe_gamma_identical(self):
        """Call and put with same parameters share the same gamma (put-call parity)."""
        ce = compute_greeks(option_type="CE", **_ATM_KWARGS)
        pe = compute_greeks(option_type="PE", **_ATM_KWARGS)
        assert (
            abs(ce["gamma"] - pe["gamma"]) < 1e-9
        ), f"CE gamma={ce['gamma']} != PE gamma={pe['gamma']}"

    def test_ce_pe_vega_identical(self):
        """Call and put with same parameters share the same vega."""
        ce = compute_greeks(option_type="CE", **_ATM_KWARGS)
        pe = compute_greeks(option_type="PE", **_ATM_KWARGS)
        assert (
            abs(ce["vega"] - pe["vega"]) < 1e-9
        ), f"CE vega={ce['vega']} != PE vega={pe['vega']}"

    def test_invalid_option_type_raises(self):
        """Unsupported option_type must raise ValueError — not silently produce garbage."""
        with pytest.raises(ValueError, match="option_type"):
            compute_greeks(option_type="XX", **_ATM_KWARGS)

    def test_zero_dte_raises(self):
        """time_to_expiry_days <= 0 must raise ValueError."""
        with pytest.raises(ValueError, match="time_to_expiry_days"):
            compute_greeks(
                option_type="CE",
                underlying_price=18000,
                strike=18000,
                time_to_expiry_days=0,
                risk_free_rate=0.065,
                implied_volatility=0.20,
            )

    def test_zero_iv_raises(self):
        """implied_volatility <= 0 must raise ValueError."""
        with pytest.raises(ValueError, match="implied_volatility"):
            compute_greeks(
                option_type="CE",
                underlying_price=18000,
                strike=18000,
                time_to_expiry_days=30,
                risk_free_rate=0.065,
                implied_volatility=0.0,
            )

    def test_deep_itm_ce_delta_near_one(self):
        """Deep ITM call (S >> K) should have delta very close to 1.0."""
        result = compute_greeks(
            option_type="CE",
            underlying_price=20000.0,
            strike=15000.0,
            time_to_expiry_days=30.0,
            risk_free_rate=0.065,
            implied_volatility=0.20,
        )
        assert (
            result["delta"] > 0.95
        ), f"Deep ITM CE delta should be near 1.0, got {result['delta']}"

    def test_deep_otm_ce_delta_near_zero(self):
        """Deep OTM call (S << K) should have delta very close to 0.0."""
        result = compute_greeks(
            option_type="CE",
            underlying_price=15000.0,
            strike=20000.0,
            time_to_expiry_days=30.0,
            risk_free_rate=0.065,
            implied_volatility=0.20,
        )
        assert (
            result["delta"] < 0.05
        ), f"Deep OTM CE delta should be near 0.0, got {result['delta']}"
