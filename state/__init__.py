"""
State schemas + runtime validation for AAATS JSON state files.

Phase D.3 — schema-drift assertions on startup. Every JSON state file with
a writer + reader pair has a pydantic model here; readers/writers route
through validated helpers so a schema mismatch surfaces at the boundary
instead of as a stale-data silent failure days later.
"""

from state.schemas import (
    HaltStateSchema,
    HeartbeatSchema,
    PaperPositionsSchema,
    RiskEngineStateSchema,
    ShareEqualityMismatchesSchema,
    SchemaValidationError,
    load_validated,
    save_validated,
    validate_all_state_files,
)

__all__ = [
    "HaltStateSchema",
    "HeartbeatSchema",
    "PaperPositionsSchema",
    "RiskEngineStateSchema",
    "ShareEqualityMismatchesSchema",
    "SchemaValidationError",
    "load_validated",
    "save_validated",
    "validate_all_state_files",
]
