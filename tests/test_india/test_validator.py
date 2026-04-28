"""
Tests for markets/india/validator.py.
All tests mock AuditTrail — no real database writes.
Circuit breaker tests use config.india.circuit_limits with a real dict so that
_get_circuit_pct() returns the intended percentage.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from markets.india.validator import validate_bars

# ── Helpers ───────────────────────────────────────────────────────────────────


def _bar(
    ts: str,
    open: float = 100.0,
    high: float = 105.0,
    low: float = 99.0,
    close: float = 103.0,
    volume: float = 1000.0,
) -> dict:
    return {
        "timestamp": pd.Timestamp(ts, tz="UTC"),
        "open": open,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _df(*bars) -> pd.DataFrame:
    return pd.DataFrame(list(bars))


def _config(symbol: str = "RELIANCE", circuit_pct: int = 20) -> MagicMock:
    """Return a MagicMock config with a real dict for circuit_limits."""
    cfg = MagicMock()
    cfg.india.circuit_limits = {symbol: circuit_pct}
    return cfg


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestValidateBars:
    def test_valid_bars_pass_through(self):
        """All valid bars are returned unchanged with correct columns."""
        df = _df(_bar("2024-01-01"), _bar("2024-01-02"), _bar("2024-01-03"))
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "RELIANCE", _config())

        assert len(clean) == 3
        assert rejections == []
        assert list(clean.columns) == [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

    def test_null_field_rejected(self):
        """Bar with a null field is rejected and removed from the clean DataFrame."""
        b = _bar("2024-01-01")
        b["close"] = None
        df = _df(b)
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "RELIANCE", _config())

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "null_field" in rejections[0]["reasons"]

    def test_zero_volume_rejected(self):
        """Bar with volume == 0 is rejected."""
        df = _df(_bar("2024-01-01", volume=0.0))
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "RELIANCE", _config())

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "zero_volume" in rejections[0]["reasons"]

    def test_high_lt_low_rejected(self):
        """Bar where high < low is rejected."""
        df = _df(_bar("2024-01-01", high=95.0, low=99.0))
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "RELIANCE", _config())

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "high_lt_low" in rejections[0]["reasons"]

    def test_spike_gt_20pct_rejected_lt_20pct_passes(self):
        """Bar with >20% close spike is rejected; <20% spike passes through."""
        df = _df(
            _bar("2024-01-01", close=100.0),  # baseline
            _bar("2024-01-02", close=115.0),  # 15% — passes
            _bar("2024-01-03", close=140.0),  # 21.7% from 115 — rejected
        )
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "RELIANCE", _config())

        assert len(clean) == 2
        assert len(rejections) == 1
        assert "price_spike_gt_20pct" in rejections[0]["reasons"]

    def test_out_of_order_timestamp_rejected(self):
        """Bar whose timestamp <= previous bar's timestamp is rejected."""
        df = _df(
            _bar("2024-01-03"),
            _bar("2024-01-01"),  # earlier than 2024-01-03 — rejected
            _bar("2024-01-05"),  # strictly after — passes
        )
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "RELIANCE", _config())

        assert len(rejections) == 1
        assert "out_of_order_timestamp" in rejections[0]["reasons"]
        assert len(clean) == 2

    def test_upper_circuit_limit_rejected(self):
        """Bar whose close is at the NSE upper circuit limit is rejected.

        Uses circuit_pct=10 so the test is independent of the 20% spike check.
        A close of 110 on prev_close of 100 hits the 10% upper circuit exactly.
        """
        cfg = _config("SBIN", circuit_pct=10)
        df = _df(
            _bar("2024-01-01", close=100.0),           # baseline
            _bar("2024-01-02", close=110.0, high=110.0),  # exactly at 10% upper circuit
        )
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "SBIN", cfg)

        assert len(rejections) == 1
        assert "upper_circuit_limit" in rejections[0]["reasons"]
        assert len(clean) == 1

    def test_lower_circuit_limit_rejected(self):
        """Bar whose close is at the NSE lower circuit limit is rejected.

        Uses circuit_pct=5 so the test is independent of the 20% spike check.
        A close of 95 on prev_close of 100 hits the 5% lower circuit exactly.
        """
        cfg = _config("TATASTEEL", circuit_pct=5)
        df = _df(
            _bar("2024-01-01", close=100.0),          # baseline
            _bar("2024-01-02", close=95.0, low=95.0),  # exactly at 5% lower circuit
        )
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "TATASTEEL", cfg)

        assert len(rejections) == 1
        assert "lower_circuit_limit" in rejections[0]["reasons"]
        assert len(clean) == 1

    def test_rejection_logged_to_audit_trail(self):
        """Every rejected bar produces exactly one REJECTION entry in the audit trail."""
        df = _df(_bar("2024-01-01", volume=0.0))
        mock_audit = MagicMock()
        with patch("markets.india.validator.AuditTrail", return_value=mock_audit):
            validate_bars(df, "INFY", _config())

        assert mock_audit.append.call_count == 1
        kwargs = mock_audit.append.call_args.kwargs
        assert kwargs["event_type"] == "REJECTION"
        assert kwargs["result"] == "REJECTED"
        assert kwargs["market"] == "india"
        assert kwargs["module"] == "validator"

    def test_clean_bars_count_correct_with_mixed_input(self):
        """Only clean bars are returned; rejection count matches invalid bars."""
        df = _df(
            _bar("2024-01-01", close=100.0),           # valid — baseline
            _bar("2024-01-02", volume=0.0),             # rejected: zero_volume
            _bar("2024-01-03", close=103.0),            # valid
            _bar("2024-01-04", high=90.0, low=99.0),    # rejected: high_lt_low
            _bar("2024-01-05", close=106.0),            # valid
        )
        with patch("markets.india.validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_bars(df, "RELIANCE", _config())

        assert len(clean) == 3
        assert len(rejections) == 2
