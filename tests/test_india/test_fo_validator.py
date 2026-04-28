"""
Tests for markets/india/fo_validator.py.
All tests mock AuditTrail — no real database writes.
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from markets.india.fo_validator import validate_option_chain

# ── Helpers ───────────────────────────────────────────────────────────────────


def _row(
    strike: float = 22000.0,
    option_type: str = "CE",
    ltp: float = 150.0,
    oi: float = 1000.0,
    change_in_oi: float = 50.0,
    iv: float = 15.0,
    bid: float = 149.0,
    ask: float = 151.0,
    volume: float = 500.0,
) -> dict:
    return {
        "strike": strike,
        "option_type": option_type,
        "ltp": ltp,
        "oi": oi,
        "change_in_oi": change_in_oi,
        "iv": iv,
        "bid": bid,
        "ask": ask,
        "volume": volume,
    }


def _df(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def _config(
    lot_size: int = 25,
    valid_strikes: list | None = None,
    spot_price: float | None = None,
    far_otm_pct: float = 30.0,
    underlying: str = "NIFTY",
) -> MagicMock:
    cfg = MagicMock()
    cfg.india.lot_sizes = {underlying: lot_size}
    cfg.india.valid_strikes = (
        {underlying: valid_strikes} if valid_strikes is not None else {}
    )
    cfg.india.spot_prices = {underlying: spot_price} if spot_price is not None else {}
    cfg.india.far_otm_pct = far_otm_pct
    return cfg


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestValidateOptionChain:
    def test_valid_chain_passes_through(self):
        """All valid rows are returned unchanged with no rejections."""
        # OI=1000 is a multiple of lot_size=25 (40 lots); IV > 0; bid/ask non-zero
        df = _df(
            _row(
                strike=22000.0,
                option_type="CE",
                oi=1000.0,
                iv=15.0,
                bid=149.0,
                ask=151.0,
            ),
            _row(
                strike=22000.0,
                option_type="PE",
                oi=1025.0,
                iv=14.0,
                bid=148.0,
                ask=150.0,
            ),
        )
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", _config())

        assert len(clean) == 2
        assert rejections == []

    def test_iv_zero_rejected(self):
        """Row with IV == 0 is rejected with reason iv_zero_or_negative."""
        df = _df(_row(iv=0.0, oi=25.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", _config())

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "iv_zero_or_negative" in rejections[0]["reasons"]

    def test_iv_negative_rejected(self):
        """Row with IV < 0 is also rejected with reason iv_zero_or_negative."""
        df = _df(_row(iv=-5.0, oi=25.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", _config())

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "iv_zero_or_negative" in rejections[0]["reasons"]

    def test_oi_zero_rejected(self):
        """Row with OI == 0 is rejected with reason oi_zero (illiquid strike)."""
        df = _df(_row(oi=0.0, iv=15.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", _config())

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "oi_zero" in rejections[0]["reasons"]

    def test_zero_bid_and_ask_rejected(self):
        """Row where both bid and ask are 0 is rejected (no market)."""
        df = _df(_row(bid=0.0, ask=0.0, oi=25.0, iv=15.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", _config())

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "no_market_bid_ask_zero" in rejections[0]["reasons"]

    def test_far_otm_strike_rejected_when_enabled(self):
        """Strike beyond far_otm_pct% of spot is rejected when spot_price is configured."""
        # spot=22000, 30% threshold → max distance = 6600
        # strike=29000 → |29000 - 22000| = 7000 > 6600 → rejected
        cfg = _config(spot_price=22000.0, far_otm_pct=30.0)
        df = _df(_row(strike=29000.0, oi=25.0, iv=15.0, bid=1.0, ask=2.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", cfg)

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "far_otm_strike" in rejections[0]["reasons"]

    def test_valid_otm_accepted_within_threshold(self):
        """Strike within far_otm_pct% of spot is accepted."""
        # spot=22000, 30% threshold → max distance = 6600
        # strike=22500 → |22500 - 22000| = 500 < 6600 → accepted
        cfg = _config(spot_price=22000.0, far_otm_pct=30.0)
        df = _df(_row(strike=22500.0, oi=25.0, iv=15.0, bid=149.0, ask=151.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", cfg)

        assert len(clean) == 1
        assert rejections == []

    def test_rejection_logged_to_audit_trail(self):
        """Every rejected row produces exactly one REJECTION audit entry."""
        df = _df(_row(iv=0.0, oi=25.0))
        mock_audit = MagicMock()
        with patch("markets.india.fo_validator.AuditTrail", return_value=mock_audit):
            validate_option_chain(df, "NIFTY", _config())

        assert mock_audit.append.call_count == 1
        kwargs = mock_audit.append.call_args.kwargs
        assert kwargs["event_type"] == "REJECTION"
        assert kwargs["result"] == "REJECTED"
        assert kwargs["market"] == "india"
        assert kwargs["module"] == "fo_validator"

    def test_multiple_rejections_on_mixed_input(self):
        """Only clean rows are returned; rejection count matches invalid rows."""
        df = _df(
            _row(strike=22000.0, oi=1000.0, iv=15.0, bid=149.0, ask=151.0),  # valid
            _row(
                strike=22100.0, oi=0.0, iv=12.0, bid=130.0, ask=132.0
            ),  # rejected: oi_zero
            _row(
                strike=22200.0, oi=975.0, iv=0.0, bid=100.0, ask=102.0
            ),  # rejected: iv_zero
            _row(strike=22300.0, oi=1050.0, iv=11.0, bid=90.0, ask=91.0),  # valid
        )
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", _config())

        assert len(clean) == 2
        assert len(rejections) == 2

    def test_empty_dataframe_returns_empty(self):
        """Empty input returns empty clean DataFrame with no rejections and no error."""
        empty_df = pd.DataFrame(
            columns=[
                "strike",
                "option_type",
                "ltp",
                "oi",
                "change_in_oi",
                "iv",
                "bid",
                "ask",
                "volume",
            ]
        )
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(empty_df, "NIFTY", _config())

        assert clean.empty
        assert rejections == []

    def test_far_otm_check_skipped_when_no_spot_price(self):
        """Far-OTM check is not applied when spot_price is not configured."""
        # Without spot_price, even a very far strike should pass the OTM check
        cfg = _config(spot_price=None)
        df = _df(_row(strike=50000.0, oi=25.0, iv=15.0, bid=1.0, ask=2.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", cfg)

        # Should pass (only the OTM check is skipped; no other violations)
        assert len(clean) == 1
        assert rejections == []

    def test_lot_size_violation_rejected(self):
        """Row where OI is not an integer multiple of lot_size is rejected."""
        # lot_size=25, OI=13 → 13 % 25 = 13 ≠ 0 → rejected
        cfg = _config(lot_size=25)
        df = _df(_row(oi=13.0, iv=15.0, bid=149.0, ask=151.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", cfg)

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "oi_not_lot_multiple" in rejections[0]["reasons"]

    def test_strike_not_in_valid_list_rejected(self):
        """Row whose strike is not in the configured valid strike list is rejected."""
        cfg = _config(valid_strikes=[22000.0, 22100.0, 22200.0])
        df = _df(_row(strike=21999.0, oi=25.0, iv=15.0, bid=149.0, ask=151.0))
        with patch("markets.india.fo_validator.AuditTrail", return_value=MagicMock()):
            clean, rejections = validate_option_chain(df, "NIFTY", cfg)

        assert len(clean) == 0
        assert len(rejections) == 1
        assert "strike_not_in_valid_list" in rejections[0]["reasons"]
