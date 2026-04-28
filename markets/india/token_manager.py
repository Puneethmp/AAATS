"""
Angel One SmartAPI session renewal via TOTP.
Runs before India market open (8:00 AM IST). Failure halts the India module + fires an alert.

SmartConnect client is injected via dependency injection.
Production: pass SmartConnect(api_key).
Tests: pass MagicMock().
"""

from datetime import datetime
from typing import Callable, Optional

import pyotp
import pytz

from foundation.audit_trail import AuditTrail
from foundation.kill_switch import halt
from foundation.logger import get_logger

_IST = pytz.timezone("Asia/Kolkata")
_log = get_logger("india", "token_manager")


class TokenManager:
    """
    Manages Angel One SmartAPI session tokens with daily TOTP-based renewal.

    Angel One tokens expire daily at midnight IST. Call renew_session() before
    market open each day. get_auth_token() returns the cached token until expiry.
    """

    def __init__(
        self,
        smart_connect_client,
        config,
        alert_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._client = smart_connect_client
        self._config = config
        self._alert_fn = (
            alert_fn if alert_fn is not None else (lambda msg: _log.warning(msg))
        )
        self._session: Optional[dict] = None
        self._renewal_date: Optional[object] = None  # datetime.date in IST timezone
        self._audit = AuditTrail()

    def renew_session(self) -> dict:
        """
        Generate a fresh TOTP and authenticate with Angel One SmartAPI.

        Returns:
            {"auth_token": str, "refresh_token": str, "feed_token": str}

        Raises:
            RuntimeError: if authentication fails (India market is halted before raising).
        """
        totp = pyotp.TOTP(self._config.india.angel_totp_secret).now()

        try:
            response = self._client.generateSession(
                self._config.india.angel_client_id,
                self._config.india.angel_pin,
                totp,
            )
        except Exception as exc:
            self._handle_auth_failure(f"generateSession raised: {exc}")
            raise RuntimeError(f"Angel One session renewal failed: {exc}") from exc

        if not response or not response.get("status"):
            msg = (
                response.get("message", "Unknown auth failure")
                if response
                else "Empty response from generateSession"
            )
            self._handle_auth_failure(msg)
            raise RuntimeError(f"Angel One generateSession failed: {msg}")

        data = response["data"]
        self._session = {
            "auth_token": data["jwtToken"],
            "refresh_token": data["refreshToken"],
            "feed_token": data["feedToken"],
        }
        self._renewal_date = datetime.now(_IST).date()

        self._audit.append(
            market="india",
            module="token_manager",
            event_type="TOKEN_RENEWAL",
            details={"client_id": self._config.india.angel_client_id},
            result="SUCCESS",
            reason="Session renewed successfully",
        )
        _log.info(
            "Angel One session renewed", client_id=self._config.india.angel_client_id
        )
        return dict(self._session)

    def get_auth_token(self) -> str:
        """
        Return the cached JWT auth token.

        Raises:
            RuntimeError: if renew_session() has not been called yet this session.
        """
        if self._session is None:
            raise RuntimeError(
                "No active session — call renew_session() before get_auth_token()."
            )
        return self._session["auth_token"]

    def is_token_valid(self) -> bool:
        """
        Return True only if renew_session was called today (IST) and the token has not expired.
        Angel One tokens expire daily at midnight IST — renewed yesterday is invalid today.
        """
        if self._session is None or self._renewal_date is None:
            return False
        return self._renewal_date == datetime.now(_IST).date()

    def _handle_auth_failure(self, reason: str) -> None:
        msg = f"Angel One auth failure: {reason}"
        _log.error(msg)
        try:
            self._audit.append(
                market="india",
                module="token_manager",
                event_type="TOKEN_RENEWAL",
                details={
                    "client_id": self._config.india.angel_client_id,
                    "error": reason,
                },
                result="FAILURE",
                reason=msg,
            )
        except Exception:
            pass  # Audit failure must not suppress the halt
        halt(market="india", reason=msg, triggered_by="token_manager")
        self._alert_fn(msg)
