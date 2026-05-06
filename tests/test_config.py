"""
Tests for config/settings.py.
Verifies that Pydantic v2 validators enforce risk caps and reject invalid values.
"""

import pytest
from pydantic import ValidationError


class TestUSConfig:
    def test_risk_cap_rejected_above_015(self):
        from config.settings import USConfig

        with pytest.raises(ValidationError) as exc:
            USConfig(
                alpaca_api_key="key",
                alpaca_secret_key="secret",
                max_risk_per_trade=0.02,
            )
        assert "1.5%" in str(exc.value) or "0.015" in str(exc.value)

    def test_risk_cap_accepted_at_015(self):
        from config.settings import USConfig

        cfg = USConfig(
            alpaca_api_key="key",
            alpaca_secret_key="secret",
            max_risk_per_trade=0.015,
        )
        assert cfg.max_risk_per_trade == 0.015

    def test_risk_cap_accepted_below_015(self):
        from config.settings import USConfig

        cfg = USConfig(
            alpaca_api_key="key",
            alpaca_secret_key="secret",
            max_risk_per_trade=0.005,
        )
        assert cfg.max_risk_per_trade == 0.005

    def test_drawdown_halt_must_be_negative(self):
        from config.settings import USConfig

        with pytest.raises(ValidationError):
            USConfig(
                alpaca_api_key="key",
                alpaca_secret_key="secret",
                drawdown_halt=0.15,
            )

    def test_defaults_are_safe(self):
        from config.settings import USConfig

        cfg = USConfig(alpaca_api_key="key", alpaca_secret_key="secret")
        assert cfg.max_risk_per_trade == 0.015
        assert cfg.drawdown_halt == -0.15
        assert cfg.alpaca_base_url == "https://paper-api.alpaca.markets"


class TestIndiaConfig:
    def _base(self, **kwargs):
        return dict(
            angel_api_key="key",
            angel_client_id="A12345",
            angel_pin="1234",
            angel_totp_secret="totp",
            **kwargs,
        )

    def test_equity_risk_cap_rejected_above_015(self):
        from config.settings import IndiaConfig

        with pytest.raises(ValidationError) as exc:
            IndiaConfig(**self._base(max_risk_per_trade=0.02))
        assert "1.5%" in str(exc.value) or "0.015" in str(exc.value)

    def test_fo_risk_cap_rejected_above_010(self):
        from config.settings import IndiaConfig

        with pytest.raises(ValidationError) as exc:
            IndiaConfig(**self._base(fo_max_risk_per_trade=0.015))
        assert "1.0%" in str(exc.value) or "0.010" in str(exc.value)

    def test_fo_risk_cap_accepted_at_010(self):
        from config.settings import IndiaConfig

        cfg = IndiaConfig(**self._base(fo_max_risk_per_trade=0.010))
        assert cfg.fo_max_risk_per_trade == 0.010

    def test_equity_risk_cap_accepted_at_015(self):
        from config.settings import IndiaConfig

        cfg = IndiaConfig(**self._base(max_risk_per_trade=0.015))
        assert cfg.max_risk_per_trade == 0.015

    def test_drawdown_halt_must_be_negative(self):
        from config.settings import IndiaConfig

        with pytest.raises(ValidationError):
            IndiaConfig(**self._base(drawdown_halt=0.0))

    def test_angel_credentials_stored(self):
        from config.settings import IndiaConfig

        cfg = IndiaConfig(**self._base())
        assert cfg.angel_api_key == "key"
        assert cfg.angel_client_id == "A12345"
        assert cfg.angel_totp_secret == "totp"


class TestRiskConfig:
    def test_total_drawdown_must_be_negative(self):
        from config.settings import RiskConfig

        with pytest.raises(ValidationError):
            RiskConfig(total_drawdown_halt=0.20)

    def test_defaults_are_safe(self):
        from config.settings import RiskConfig

        cfg = RiskConfig()
        assert cfg.total_drawdown_halt == -0.20
        assert cfg.max_total_deployment == 0.40
