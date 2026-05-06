"""DAO sub-package.

Each module exposes async functions that wrap one Postgres table or Redis
keyspace. No business logic, no protected-subsystem reasoning — pure data
access.

Import policy (per κ1 req 11):
    Risk-critical decisions read ONLY via `read_durable_*` functions
    (Postgres). Cached / fast-path reads (`read_cached_*`) are for
    dashboards, the bot, and other non-money-bearing consumers.
"""

__all__ = [
    "audit_log",
    "halt",
    "orders",
    "positions",
    "reconciliation",
    "mode",
    "heartbeat",
    "paper_trades",
    "engine_status",
]
