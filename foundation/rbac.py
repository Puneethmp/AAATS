"""
Role-Based Access Control (RBAC) for AAATS.

Defines roles and permissions to control who can:
  - Read data (VIEWER)
  - Execute trades (TRADER)
  - Modify system settings (ADMIN)
  - Emergency halt (OPERATOR)

Usage:
    from foundation.rbac import RBACManager, Role
    rbac = RBACManager()
    rbac.require_permission("live_trading", current_user="Puneeth", role=Role.ADMIN)
"""

from __future__ import annotations

from enum import Enum
from foundation.logger import get_logger

_log = get_logger("system", "rbac")


class Role(str, Enum):
    VIEWER = "viewer"
    TRADER = "trader"
    OPERATOR = "operator"
    ADMIN = "admin"


_PERMISSIONS: dict[str, list[Role]] = {
    "view_dashboard": [Role.VIEWER, Role.TRADER, Role.OPERATOR, Role.ADMIN],
    "view_positions": [Role.VIEWER, Role.TRADER, Role.OPERATOR, Role.ADMIN],
    "view_pnl": [Role.VIEWER, Role.TRADER, Role.OPERATOR, Role.ADMIN],
    "paper_trading": [Role.TRADER, Role.OPERATOR, Role.ADMIN],
    "live_trading": [Role.ADMIN],
    "emergency_halt": [Role.OPERATOR, Role.ADMIN],
    "emergency_resume": [Role.ADMIN],
    "modify_strategy": [Role.ADMIN],
    "rotate_secrets": [Role.ADMIN],
    "view_audit_log": [Role.OPERATOR, Role.ADMIN],
}

_USERS: dict[str, Role] = {
    "Puneeth": Role.ADMIN,
    "system": Role.TRADER,
}


class RBACManager:
    """Lightweight RBAC without a database — suitable for single-user personal trading."""

    def __init__(self, users: dict[str, Role] | None = None) -> None:
        self._users = users or _USERS.copy()

    def get_role(self, user: str) -> Role:
        role = self._users.get(user, Role.VIEWER)
        _log.debug(f"RBAC: {user} has role {role.value}")
        return role

    def has_permission(self, permission: str, user: str) -> bool:
        role = self.get_role(user)
        allowed_roles = _PERMISSIONS.get(permission, [])
        return role in allowed_roles

    def require_permission(self, permission: str, user: str) -> None:
        """Raise PermissionError if user lacks the required permission."""
        if not self.has_permission(permission, user):
            role = self.get_role(user)
            msg = (
                f"RBAC denied: user='{user}' role='{role.value}' "
                f"does not have permission '{permission}'"
            )
            _log.warning(msg)
            raise PermissionError(msg)
        _log.debug(f"RBAC allowed: {user} → {permission}")

    def add_user(self, user: str, role: Role) -> None:
        self._users[user] = role
        _log.info(f"RBAC: added user '{user}' with role '{role.value}'")

    def remove_user(self, user: str) -> None:
        self._users.pop(user, None)
        _log.info(f"RBAC: removed user '{user}'")
