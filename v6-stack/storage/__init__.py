"""AAATS v6 storage layer (Phase κ1 scaffolding).

Standalone package. NOT imported by any v5 module. Engine container in κ4
will import from here; protected modules at the workspace root remain
untouched until operator approves Gate κ-A in κ3.

Submodules:
  storage.clock     — UTC + monotonic timestamp helpers (κ1 req 9)
  storage.postgres  — asyncpg pool + transaction primitive
  storage.redis     — async Redis wrapper, key-namespace registry
  storage.audit     — DB transaction audit logger (κ1 req 6)
  storage.dao.*     — per-table DAOs

Critical invariants enforced by this package:
  - Risk-critical reads (positions, halt, mode, orders, audit_log) call
    *only* `read_durable_*` methods. These hit Postgres directly. Redis is a
    perf cache and is *never* consulted on the risk decision path (κ1 req 11).
  - All timestamps are UTC `TIMESTAMPTZ` in storage; module-level helpers
    use `datetime.timezone.utc` and `time.monotonic_ns` (κ1 req 9).
  - Transaction audit (storage.audit) writes a row per tx for shadow-mode
    readiness (κ1 req 6).
  - No automatic data correction. Reconciliation mismatches surface to the
    operator only (κ1 req 10).
"""

__all__ = [
    "clock",
    "postgres",
    "redis",
    "audit",
    "dao",
]
