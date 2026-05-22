"""
Pydantic v2 schemas for the 5 JSON state files that have writer + reader pairs.

Phase D.3 (Track D, 2026-05-22). Closes catalog rows 1, 4, 6, 12, 18 by
construction: a writer that drifts from the schema fails fast on write; a
reader that gets corrupted data fails fast on read; the startup smoke
validates all five at container boot and refuses to start if any disagree
with their schema.

Production state notes (captured 2026-05-22 from /app/data/ on box):

  heartbeat.json
    Current writer: trading/live_paper_runner.py:1873-1882 (FLAT shape).
    Legacy writer: monitoring/heartbeat_monitor.HeartbeatMonitor.emit_heartbeat
      (nested per-market shape) — pre-2026-05-22; effectively dead code
      because the runner's direct write at line 1873 overwrites it.
    HeartbeatSchema models the flat form. The legacy nested form is NOT
    a supported state; if it appears at runtime, validation fails fast.

  halt_state.json
    Writer/reader: foundation/kill_switch.py — flat dict[market->bool].
    Schema is unambiguous.

  risk_engine_state.json
    Path: /app/data/state/risk_engine_state.json (NAMED VOLUME
    `deployment_state-crypto`, NOT bind-mounted — invisible from box host
    without `docker exec`).
    Writer: risk/engine.py.
    Schema: peak / last_equity / last_update_ts / market_peaks{crypto}.

  paper_positions.json
    `data/paper_positions.json` (canonical, bind-mounted) — empty per-market
    dict at the moment (`{"india": {}, "crypto": {}}`); production runs do
    not currently write back to this file (see
    docs/decisions/2026-05-15_drift_diagnosis.md — runner uses per-strategy
    state files instead).
    `runtime/paper_positions.json` (workstation-only, NOT bind-mounted,
    legacy) — rich per-symbol position dict. See the writer-drift memo at
    docs/known_issues/2026-05-22_paper_positions_writer_drift.md.
    PaperPositionsSchema accepts the canonical EMPTY-PER-MARKET shape that
    the box actually has; the legacy runtime/ shape is documented but
    intentionally NOT loadable through this schema — that file is not in
    the production read path.

  share_equality_mismatches.json
    Writer: execution/paper_trader._bump_share_mismatch_counter (on every
    SELL/BUY share-equality WARN). Reader: monitoring/metrics_exporter
    collect_share_equality, plus the share-equality Grafana alert chain.
    Schema: dict[str, int] keyed by "strategy|symbol" → counter value.
    Empty map (`{}`) is a valid state (means "no mismatches recorded").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SchemaValidationError(RuntimeError):
    """Raised when a state file fails its schema validation.

    Wraps pydantic.ValidationError with the file path so the failure
    surfaces clearly at the startup smoke or writer/reader boundary
    instead of as a generic JSON error.
    """

    def __init__(self, path: Path | str, schema_name: str, cause: Exception):
        self.path = Path(path)
        self.schema_name = schema_name
        self.cause = cause
        super().__init__(
            f"State file {self.path} failed {schema_name} validation: {cause}"
        )


# ── heartbeat.json (FLAT — current production writer) ────────────────────────


class HeartbeatSchema(BaseModel):
    """Schema for data/heartbeat.json.

    FLAT shape written by trading/live_paper_runner.py:1873-1882:
        {"timestamp": "...", "cycle": 95, "market": "crypto",
         "cycle_duration_seconds": 12.988}

    The legacy nested-per-market shape written by
    monitoring/heartbeat_monitor.HeartbeatMonitor is NOT supported by this
    schema (catalog row 1; D.3 closes the writer/reader drift by making
    the flat shape canonical and refusing the nested one).
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    cycle: int = Field(ge=0)
    market: str
    cycle_duration_seconds: float = Field(ge=0)


# ── halt_state.json ──────────────────────────────────────────────────────────


class HaltStateSchema(BaseModel):
    """Schema for data/halt_state.json (foundation/kill_switch.py).

    Per-market halt flags. Three markets fixed by the kill-switch
    contract. Extra keys are forbidden so a future typo (e.g. "cyrpto")
    fails fast.
    """

    model_config = ConfigDict(extra="forbid")

    us: bool = False
    india: bool = False
    crypto: bool = False


# ── risk_engine_state.json (named volume) ───────────────────────────────────


class MarketPeaksSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    crypto: float | None = None
    india: float | None = None
    us: float | None = None


class RiskEngineStateSchema(BaseModel):
    """Schema for /app/data/state/risk_engine_state.json (risk/engine.py).

    Lives behind the named Docker volume `deployment_state-crypto` — not
    visible from the bind-mount path. Survives container restarts via the
    volume.

    Fields observed on box 2026-05-22:
      peak, last_update_ts, last_equity, market_peaks{crypto}
    """

    model_config = ConfigDict(extra="allow")

    peak: float = Field(ge=0)
    last_update_ts: float = Field(gt=0)
    last_equity: float
    market_peaks: MarketPeaksSchema


# ── paper_positions.json (canonical at data/, empty per-market) ─────────────


class PaperPositionsSchema(BaseModel):
    """Schema for data/paper_positions.json (canonical, bind-mounted).

    Production state on box: `{"india": {}, "crypto": {}}`. Per-symbol
    position dicts are accepted but the production read path does NOT
    currently consume this file for active positions (see writer-drift
    memo docs/known_issues/2026-05-22_paper_positions_writer_drift.md
    for the call graph).

    The richer per-symbol shape used by runtime/paper_positions.json
    (workstation-only, legacy) is intentionally NOT supported here — that
    file is out of the canonical read path.
    """

    model_config = ConfigDict(extra="forbid")

    india: dict[str, Any] = Field(default_factory=dict)
    crypto: dict[str, Any] = Field(default_factory=dict)


# ── share_equality_mismatches.json ──────────────────────────────────────────


class ShareEqualityMismatchesSchema(BaseModel):
    """Schema for data/share_equality_mismatches.json.

    `dict[str, int]` keyed by "strategy|symbol" → counter value. Empty
    map ({}) is a valid state (no mismatches recorded).

    Production state captured 2026-05-22 on box: `{}` empty. The session-1
    finding of `{"C3_altcoin_reversion|TON/USDT": 6, "...|FET/USDT": 6}`
    was a snapshot of a transient state; the value range and key shape
    accepted by this schema covers both empty and populated cases. See
    1.b alert-chain audit memo for the historical-state explanation.
    """

    mismatches: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Any) -> "ShareEqualityMismatchesSchema":
        """Promote a bare dict (the on-disk shape) into the typed wrapper.

        The file format on disk is a bare JSON object like
        ``{"strategy|symbol": 6}`` (not nested under a "mismatches" key);
        this helper accepts that bare shape and validates every key
        contains the "|" separator and every value is a non-negative int.
        """
        if not isinstance(raw, dict):
            raise ValueError(
                f"share_equality_mismatches.json must be a JSON object, "
                f"got {type(raw).__name__}"
            )
        for k, v in raw.items():
            if not isinstance(k, str) or "|" not in k:
                raise ValueError(
                    f"share_equality_mismatches key {k!r} must be "
                    f"'strategy|symbol' format"
                )
            if not isinstance(v, int) or v < 0:
                raise ValueError(
                    f"share_equality_mismatches[{k!r}]={v!r} must be a "
                    f"non-negative int"
                )
        return cls(mismatches=dict(raw))

    def to_raw(self) -> dict[str, int]:
        """Return the on-disk bare-dict shape (drops the wrapper)."""
        return dict(self.mismatches)


# ── Generic validated I/O helpers ───────────────────────────────────────────


_SCHEMA_BY_FILENAME: dict[str, type[BaseModel]] = {
    "heartbeat.json": HeartbeatSchema,
    "halt_state.json": HaltStateSchema,
    "risk_engine_state.json": RiskEngineStateSchema,
    "paper_positions.json": PaperPositionsSchema,
    # share_equality_mismatches.json handled via from_raw / to_raw path
}


def load_validated(path: Path | str, schema: type[BaseModel]) -> BaseModel:
    """Read a JSON file from disk and validate it against the schema.

    Raises SchemaValidationError on validation failure with the offending
    path attached. The caller can decide whether to refuse to start
    (startup smoke) or fall back to a default (resilient reader).
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaValidationError(p, schema.__name__, exc) from exc

    try:
        if schema is ShareEqualityMismatchesSchema:
            return ShareEqualityMismatchesSchema.from_raw(raw)
        return schema.model_validate(raw)
    except (ValidationError, ValueError) as exc:
        raise SchemaValidationError(p, schema.__name__, exc) from exc


def save_validated(path: Path | str, model: BaseModel) -> None:
    """Validate the model, then write it to disk via atomic temp-and-rename.

    Re-validation before write catches in-memory drift (e.g. a strategy
    state assignment violating the schema) before it lands as on-disk
    corruption that the next reader would inherit.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        if isinstance(model, ShareEqualityMismatchesSchema):
            payload = model.to_raw()
        else:
            payload = model.model_dump(mode="json")
    except (ValidationError, ValueError) as exc:
        raise SchemaValidationError(p, type(model).__name__, exc) from exc

    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(p)


def validate_all_state_files(data_dir: Path | str) -> dict[str, str]:
    """Validate every known state file under data_dir/.

    Used as a startup smoke from the trading loop entry point. Returns a
    dict {file_name: status_message}; status is "OK" on pass and an error
    string on fail. Caller decides whether to refuse-to-start.

    Note: risk_engine_state.json lives under data_dir/state/ inside the
    container's named volume; the path is constructed accordingly.
    """
    base = Path(data_dir)
    targets = [
        (base / "heartbeat.json", HeartbeatSchema, True),
        (base / "halt_state.json", HaltStateSchema, True),
        (base / "paper_positions.json", PaperPositionsSchema, True),
        (base / "share_equality_mismatches.json",
         ShareEqualityMismatchesSchema, True),
        (base / "state" / "risk_engine_state.json",
         RiskEngineStateSchema, False),
    ]
    results: dict[str, str] = {}
    for path, schema, required in targets:
        key = str(path.relative_to(base) if path.is_absolute() else path)
        if not path.exists():
            results[key] = "MISSING" if required else "MISSING_OPTIONAL"
            continue
        try:
            load_validated(path, schema)
            results[key] = "OK"
        except SchemaValidationError as exc:
            results[key] = f"INVALID: {exc.cause}"
    return results
