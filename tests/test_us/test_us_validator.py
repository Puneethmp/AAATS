"""
Tests for markets/us/validator.py.
All tests mock AuditTrail — no real database writes.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

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


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestValidateBars:
    def test_valid_bars_pass_through(self):
        """All valid bars are returned unchanged with correct columns."""
        df = _df(_bar("2024-01-01"), _bar("2024-01-02"), _bar("2024-01-03"))
        with patch("markets.us.validator.AuditTrail", return_value=MagicMock()):
            from markets.us.validator import validate_bars

            clean, rejections = validate_bars(df, "AAPL")
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
        with patch("markets.us.validator.AuditTrail", return_value=MagicMock()):
            from markets.us.validator import validate_bars

            clean, rejections = validate_bars(df, "AAPL")
        assert len(clean) == 0
        assert len(rejections) == 1
        assert "null_field" in rejections[0]["reasons"]

    def test_zero_volume_rejected(self):
        """Bar with volume == 0 is rejected."""
        df = _df(_bar("2024-01-01", volume=0.0))
        with patch("markets.us.validator.AuditTrail", return_value=MagicMock()):
            from markets.us.validator import validate_bars

            clean, rejections = validate_bars(df, "AAPL")
        assert len(clean) == 0
        assert len(rejections) == 1
        assert "zero_volume" in rejections[0]["reasons"]

    def test_high_lt_low_rejected(self):
        """Bar where high < low is rejected."""
        df = _df(_bar("2024-01-01", high=95.0, low=99.0))
        with patch("markets.us.validator.AuditTrail", return_value=MagicMock()):
            from markets.us.validator import validate_bars

            clean, rejections = validate_bars(df, "AAPL")
        assert len(clean) == 0
        assert len(rejections) == 1
        assert "high_lt_low" in rejections[0]["reasons"]

    def test_spike_gt_20pct_rejected_lt_20pct_passes(self):
        """Bar with >20% close spike is rejected; <20% spike passes through."""
        df = _df(
            _bar("2024-01-01", close=100.0),  # baseline
            _bar("2024-01-02", close=115.0),  # 15% from 100 — passes
            _bar("2024-01-03", close=140.0),  # 21.7% from 115 — rejected
        )
        with patch("markets.us.validator.AuditTrail", return_value=MagicMock()):
            from markets.us.validator import validate_bars

            clean, rejections = validate_bars(df, "AAPL")
        assert len(clean) == 2
        assert len(rejections) == 1
        assert "price_spike_gt_20pct" in rejections[0]["reasons"]

    def test_out_of_order_timestamp_rejected(self):
        """Bar whose timestamp <= previous bar's timestamp is rejected."""
        df = _df(
            _bar("2024-01-03"),
            _bar("2024-01-01"),  # earlier than 2024-01-03 — rejected
            _bar("2024-01-05"),  # strictly after 2024-01-01 — passes
        )
        with patch("markets.us.validator.AuditTrail", return_value=MagicMock()):
            from markets.us.validator import validate_bars

            clean, rejections = validate_bars(df, "AAPL")
        assert len(rejections) == 1
        assert "out_of_order_timestamp" in rejections[0]["reasons"]
        assert len(clean) == 2

    def test_rejection_logged_to_audit_trail(self):
        """Every rejected bar produces exactly one REJECTION entry in the audit trail."""
        df = _df(_bar("2024-01-01", volume=0.0))
        mock_audit = MagicMock()
        with patch("markets.us.validator.AuditTrail", return_value=mock_audit):
            from markets.us.validator import validate_bars

            validate_bars(df, "TSLA")
        assert mock_audit.append.call_count == 1
        kwargs = mock_audit.append.call_args.kwargs
        assert kwargs["event_type"] == "REJECTION"
        assert kwargs["result"] == "REJECTED"
        assert kwargs["market"] == "us"
        assert kwargs["module"] == "validator"
