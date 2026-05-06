"""
Pydantic v2 configuration for AAATS.
Validates all settings at startup — fails loudly on missing keys or invalid values.
Risk caps (1.5% equity, 1.0% F&O) are enforced by validators and cannot be exceeded from config.
"""

from typing import Literal

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SystemConfig(BaseModel):
    trading_mode: Literal["paper", "live"] = "paper"
    log_level: str = "INFO"
    log_retention_days: int = 90
    health_check_interval_seconds: int = 300


class USConfig(BaseModel):
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    max_risk_per_trade: float = 0.015
    max_portfolio_exposure: float = 0.06
    drawdown_halt: float = -0.15

    @field_validator("max_risk_per_trade")
    @classmethod
    def enforce_us_risk_cap(cls, v: float) -> float:
        if v > 0.015:
            raise ValueError(
                f"US max_risk_per_trade {v} exceeds the hardcoded cap of 0.015 (1.5%). "
                "This limit exists to prevent account destruction and cannot be increased."
            )
        return v

    @field_validator("drawdown_halt")
    @classmethod
    def enforce_drawdown_negative(cls, v: float) -> float:
        if v >= 0:
            raise ValueError("drawdown_halt must be a negative value (e.g. -0.15 for -15%).")
        return v


class IndiaConfig(BaseModel):
    # Angel One SmartAPI credentials (free with demat account — no monthly subscription)
    angel_api_key: str
    angel_client_id: str       # Your Angel One login ID (e.g., REDACTED_ANGEL_CLIENT_ID)
    angel_pin: str             # Your Angel One 4-digit PIN (e.g., 9066)
    angel_totp_secret: str     # TOTP secret for automated daily session token renewal
    max_risk_per_trade: float = 0.015
    fo_max_risk_per_trade: float = 0.010
    drawdown_halt: float = -0.15

    @field_validator("max_risk_per_trade")
    @classmethod
    def enforce_india_risk_cap(cls, v: float) -> float:
        if v > 0.015:
            raise ValueError(
                f"India max_risk_per_trade {v} exceeds the hardcoded cap of 0.015 (1.5%). "
                "This limit exists to prevent account destruction and cannot be increased."
            )
        return v

    @field_validator("fo_max_risk_per_trade")
    @classmethod
    def enforce_fo_risk_cap(cls, v: float) -> float:
        if v > 0.010:
            raise ValueError(
                f"F&O fo_max_risk_per_trade {v} exceeds the hardcoded cap of 0.010 (1.0%). "
                "F&O uses leverage — the tighter cap is non-negotiable."
            )
        return v

    @field_validator("drawdown_halt")
    @classmethod
    def enforce_india_drawdown_negative(cls, v: float) -> float:
        if v >= 0:
            raise ValueError("drawdown_halt must be a negative value (e.g. -0.15 for -15%).")
        return v


class RiskConfig(BaseModel):
    total_drawdown_halt: float = -0.20
    max_total_deployment: float = 0.40

    @field_validator("total_drawdown_halt")
    @classmethod
    def enforce_total_drawdown_negative(cls, v: float) -> float:
        if v >= 0:
            raise ValueError("total_drawdown_halt must be a negative value (e.g. -0.20 for -20%).")
        return v


class AlertConfig(BaseModel):
    telegram_bot_token: str
    telegram_chat_id: str


class AppConfig(BaseSettings):
    system: SystemConfig = SystemConfig()
    us: USConfig
    india: IndiaConfig
    risk: RiskConfig = RiskConfig()
    alerts: AlertConfig

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        case_sensitive=False,
        env_file_encoding="utf-8",
    )
