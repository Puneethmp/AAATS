"""
Tests for risk/us/drawdown_guardian.py.

Covers: no drawdown, partial drawdown, halt trigger, sticky halt after
recovery, rolling peak tracking, and manual reset.

kill_switch is mocked in tests that trigger halts to prevent disk writes
and audit trail side effects.
"""

from unittest.mock import patch

from risk.us.drawdown_guardian import (
    MARKET_DRAWDOWN_HALT_PCT,
    DrawdownGuardian,
    DrawdownStatus,
)


def test_no_drawdown():
    """Rising values → drawdown=0, not halted."""
    guardian = DrawdownGuardian(peak_value=100_000.0, market="us")

    status = guardian.update(100_000.0)
    assert status.drawdown_pct == 0.0
    assert status.halted is False
    assert status.halt_reason is None
    assert isinstance(status, DrawdownStatus)

    # Rise to new high — peak updates, drawdown stays zero
    status = guardian.update(110_000.0)
    assert status.drawdown_pct == 0.0
    assert status.halted is False
    assert status.peak_value == 110_000.0


def test_partial_drawdown():
    """Value drops 10% → drawdown = -10%, not halted (threshold is -15%)."""
    guardian = DrawdownGuardian(peak_value=100_000.0, market="us")

    status = guardian.update(90_000.0)

    expected_drawdown = (90_000.0 - 100_000.0) / 100_000.0  # -0.10
    assert abs(status.drawdown_pct - expected_drawdown) < 1e-10
    assert status.halted is False
    assert status.halt_reason is None
    assert status.peak_value == 100_000.0
    assert guardian.is_halted() is False


def test_halt_trigger():
    """Value drops exactly 15% → halted=True, kill_switch.halt called once."""
    with patch("risk.us.drawdown_guardian.kill_switch") as mock_ks:
        guardian = DrawdownGuardian(peak_value=100_000.0, market="us")
        status = guardian.update(85_000.0)  # -15.00% exactly

    # Drawdown: (85000 - 100000) / 100000 = -0.15 → exactly at threshold → halt
    assert abs(status.drawdown_pct - MARKET_DRAWDOWN_HALT_PCT) < 1e-10
    assert status.halted is True
    assert status.halt_reason is not None
    assert guardian.is_halted() is True

    mock_ks.halt.assert_called_once()
    call_kwargs = mock_ks.halt.call_args.kwargs
    assert call_kwargs["market"] == "us"
    assert call_kwargs["triggered_by"] == "drawdown_guardian"
    assert isinstance(call_kwargs["reason"], str)
    assert len(call_kwargs["reason"]) > 0


def test_stays_halted_after_recovery():
    """After halt, full value recovery does not clear halt — manual reset required."""
    with patch("risk.us.drawdown_guardian.kill_switch"):
        guardian = DrawdownGuardian(peak_value=100_000.0, market="us")
        guardian.update(85_000.0)  # trigger halt at -15%

    assert guardian.is_halted() is True

    # Recovery to original peak — guardian is already halted, returns early
    # without calling kill_switch again (no real disk write here)
    status = guardian.update(100_000.0)
    assert status.halted is True
    assert status.halt_reason is not None
    assert guardian.is_halted() is True


def test_peak_tracking():
    """Peak is the rolling high-water mark, not the starting value."""
    guardian = DrawdownGuardian(peak_value=100_000.0, market="us")

    # Rise to 110k — peak updates
    status = guardian.update(110_000.0)
    assert status.peak_value == 110_000.0
    assert status.drawdown_pct == 0.0

    # Drop to 96k — drawdown is relative to 110k, not original 100k
    # (96000 - 110000) / 110000 ≈ -12.73% — safely above -15% threshold
    status = guardian.update(96_000.0)
    expected_drawdown = (96_000.0 - 110_000.0) / 110_000.0
    assert abs(status.drawdown_pct - expected_drawdown) < 1e-10
    assert status.halted is False
    assert status.peak_value == 110_000.0  # peak did not revert to 100k

    # current_drawdown() must match the last update's drawdown
    assert abs(guardian.current_drawdown() - expected_drawdown) < 1e-10


def test_reset():
    """After halt, reset() clears halt flag and sets peak to current value."""
    with patch("risk.us.drawdown_guardian.kill_switch"):
        guardian = DrawdownGuardian(peak_value=100_000.0, market="us")
        guardian.update(85_000.0)  # trigger halt at -15%

    assert guardian.is_halted() is True

    guardian.reset()

    assert guardian.is_halted() is False

    # After reset, peak is the most recent value (85k).
    # Updating at 85k should show zero drawdown.
    status = guardian.update(85_000.0)
    assert status.halted is False
    assert status.drawdown_pct == 0.0
    assert status.peak_value == 85_000.0
