"""Tests for analytics.cost_model — the honest-PnL cost layer (Phase 2)."""

from __future__ import annotations

import math

import pytest

from analytics import cost_model as cm


def test_fee_bps_table():
    assert cm.fee_bps("spot", "taker") == 10.0
    assert cm.fee_bps("perp", "taker") == 5.0
    assert cm.fee_bps("perp", "maker") == 2.0


def test_fee_usd_is_fraction_of_notional():
    # 0.10% of $1000 = $1.00
    assert cm.fee_usd(1000.0, "spot", "taker") == pytest.approx(1.0)
    # perp taker 0.05% of $1000 = $0.50
    assert cm.fee_usd(1000.0, "perp", "taker") == pytest.approx(0.5)


def test_fee_and_slippage_never_negative_even_for_negative_notional():
    assert cm.fee_usd(-500.0) >= 0
    assert cm.slippage_usd(-500.0, 25.0) >= 0


def test_funding_sign_convention_long_pays_when_rate_positive():
    # rate > 0 => long pays (positive cost), short receives (negative cost)
    assert cm.funding_usd(1000.0, 0.0001, 1, "long") == pytest.approx(0.1)
    assert cm.funding_usd(1000.0, 0.0001, 1, "short") == pytest.approx(-0.1)


def test_funding_accumulates_over_intervals():
    assert cm.funding_usd(1000.0, 0.0001, 3, "long") == pytest.approx(0.3)


def test_round_trip_charges_both_legs():
    # spot taker 10bps/side on $100 entry + $100 exit = $0.10 + $0.10 fees
    rt = cm.round_trip_cost(100.0, 100.0, "spot", "taker", slippage_bps=0.0)
    assert rt.fees == pytest.approx(0.20)
    assert rt.slippage == pytest.approx(0.0)
    assert rt.funding == pytest.approx(0.0)
    assert rt.total == pytest.approx(0.20)


def test_round_trip_includes_slippage_both_sides():
    rt = cm.round_trip_cost(100.0, 100.0, "spot", "taker", slippage_bps=10.0)
    # fees 0.20 + slippage 0.10+0.10 = 0.40 total
    assert rt.total == pytest.approx(0.40)


def test_spot_has_no_funding_even_if_intervals_passed():
    rt = cm.round_trip_cost(
        100.0, instrument="spot", funding_rate=0.0, funding_intervals=5
    )
    assert rt.funding == 0.0


def test_net_pnl_subtracts_total_cost():
    # gross +$1 on a $100 round trip at 0.40 total cost => net +$0.60
    net = cm.net_pnl(1.0, 100.0, 100.0, "spot", "taker", slippage_bps=10.0)
    assert net == pytest.approx(0.60)


def test_net_pnl_can_flip_a_marginal_winner_negative():
    # This is the COST bucket: gross >= 0 but costs flip it. Mirrors Phase 0.
    net = cm.net_pnl(0.10, 100.0, 100.0, "spot", "taker", slippage_bps=10.0)
    assert net < 0


def test_exit_notional_defaults_to_entry():
    rt_default = cm.round_trip_cost(250.0, None, "spot", "taker", slippage_bps=0.0)
    rt_explicit = cm.round_trip_cost(250.0, 250.0, "spot", "taker", slippage_bps=0.0)
    assert math.isclose(rt_default.total, rt_explicit.total)
