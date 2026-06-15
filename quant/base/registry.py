"""Strategy registry — the single source of truth for "what exists and its stage".

Candidates register themselves (decorator or explicit call). The registry tracks
each candidate's lifecycle state and validation history, enforces legal lifecycle
transitions, and answers queries like "which candidates are in PAPER". This
replaces folder-by-hand stage management and makes the whole pipeline auditable
from one object.
"""

from __future__ import annotations


from .lifecycle import Lifecycle, assert_transition
from .metadata import PreRegistration, ValidationResult
from .strategy import BaseStrategy


class _Entry:
    __slots__ = ("strategy", "state", "prereg", "validations")

    def __init__(self, strategy: BaseStrategy) -> None:
        self.strategy = strategy
        self.state: Lifecycle = strategy.spec.lifecycle
        self.prereg: PreRegistration | None = None
        self.validations: list[ValidationResult] = []


class StrategyRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    # --- registration ---
    def register(self, strategy: BaseStrategy) -> BaseStrategy:
        sid = strategy.spec.id
        if sid in self._entries:
            raise ValueError(f"duplicate strategy id {sid!r}")
        self._entries[sid] = _Entry(strategy)
        return strategy

    def candidate(self, cls: type[BaseStrategy]) -> type[BaseStrategy]:
        """Class decorator: @REGISTRY.candidate registers an instance."""
        self.register(cls())
        return cls

    # --- lifecycle ---
    def attach_prereg(self, sid: str, prereg: PreRegistration) -> None:
        self._entries[sid].prereg = prereg

    def record_validation(self, result: ValidationResult) -> None:
        self._entries[result.strategy_id].validations.append(result)

    def promote(self, sid: str, to: Lifecycle) -> None:
        e = self._entries[sid]
        assert_transition(e.state, to)  # raises on illegal jump
        e.state = to

    def demote(self, sid: str, reason: str = "") -> None:
        self.promote(sid, Lifecycle.RETIRED)

    # --- queries ---
    def get(self, sid: str) -> BaseStrategy:
        return self._entries[sid].strategy

    def state_of(self, sid: str) -> Lifecycle:
        return self._entries[sid].state

    def by_state(self, state: Lifecycle) -> list[BaseStrategy]:
        return [e.strategy for e in self._entries.values() if e.state == state]

    def ids(self) -> list[str]:
        return list(self._entries)

    def summary(self) -> list[dict]:
        """One row per candidate — feeds the weekly scorecard / audit."""
        rows = []
        for sid, e in self._entries.items():
            rows.append(
                {
                    "id": sid,
                    "family": e.strategy.spec.family,
                    "state": e.state.value,
                    "prereg": bool(e.prereg),
                    "validations": len(e.validations),
                    "last_passed": (
                        e.validations[-1].passed if e.validations else None
                    ),
                }
            )
        return rows

    def __len__(self) -> int:
        return len(self._entries)


#: process-wide default registry
REGISTRY = StrategyRegistry()
