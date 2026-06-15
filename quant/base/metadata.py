"""Research & validation metadata — the audit trail attached to every candidate.

Two records:
  PreRegistration  — frozen hypothesis + params, committed BEFORE any data is
                     opened. Snooping protection. Mirrors the research/prereg/
                     spec the program already uses.
  ValidationResult — the outcome of one gate run (walk-forward, paper, etc.),
                     including the per-criterion breakdown from
                     tools/graduation/gate.py:GateResult.

These are plain dataclasses so they serialize cleanly to YAML/JSON for
research/results/ (immutable verdict log) and round-trip into the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class PreRegistration:
    """A frozen, pre-data hypothesis. Commit to origin/main before opening data."""

    strategy_id: str
    hypothesis: str  # the falsifiable H1
    mechanism: str  # the economic 'why'
    universe: str  # e.g. "frozen U30 USDT-M perps (2026-05-26)"
    horizon: str  # e.g. "monthly formation + monthly hold"
    null_model: str  # e.g. "rank-shuffle, K=1000, Bonferroni p97.5"
    frozen_params: dict[str, Any] = field(default_factory=dict)
    seed: int = 7
    registered_at: str = ""  # ISO8601; set at commit time
    prereg_ref: str = ""  # path to the committed spec .md/.yaml

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    """One gate evaluation outcome. `criteria` is GateResult.criteria verbatim."""

    strategy_id: str
    stage: str  # "walkforward" | "paper" | ...
    passed: bool
    failures: list[str] = field(default_factory=list)
    criteria: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    evaluated_at: str = ""
    seed: int = 7

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
