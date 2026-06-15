"""Lifecycle — the explicit promotion state machine.

A candidate moves RESEARCH -> BACKTEST -> WALKFORWARD -> PAPER -> LIVE, or to
RETIRED from any state on a failed gate. Transitions are one-directional except
for demotion (-> RETIRED) and an explicit operator HALT. The registry refuses
illegal jumps, so "what stage is X in" is always answerable and auditable.

The gate criteria that authorize each forward transition live in
quant.base.metadata + tools/graduation/gate.py — this module only encodes the
legal topology, not the thresholds.
"""

from __future__ import annotations

from enum import Enum


class Lifecycle(str, Enum):
    RESEARCH = "research"  # hypothesis stated, not yet pre-registered
    BACKTEST = "backtest"  # pre-registered; single-window sanity
    WALKFORWARD = "walkforward"  # the 15-fold + null gate, run once
    PAPER = "paper"  # passed WF; 90-day confirmation, entries enabled
    LIVE = "live"  # graduated paper; real minimal notional
    RETIRED = "retired"  # falsified / demoted — reference only, never live


# Allowed forward promotions. Demotion to RETIRED is legal from ANY non-retired
# state and is handled separately (assert_transition) so auto-demotion never
# needs a special case per source state.
_FORWARD: dict[Lifecycle, set[Lifecycle]] = {
    Lifecycle.RESEARCH: {Lifecycle.BACKTEST},
    Lifecycle.BACKTEST: {Lifecycle.WALKFORWARD},
    Lifecycle.WALKFORWARD: {Lifecycle.PAPER},
    Lifecycle.PAPER: {Lifecycle.LIVE},
    Lifecycle.LIVE: set(),
    Lifecycle.RETIRED: set(),
}


def can_transition(src: Lifecycle, dst: Lifecycle) -> bool:
    """True if src->dst is a legal forward promotion or a demotion to RETIRED."""
    if dst == Lifecycle.RETIRED:
        return src != Lifecycle.RETIRED
    return dst in _FORWARD.get(src, set())


def assert_transition(src: Lifecycle, dst: Lifecycle) -> None:
    """Raise ValueError on an illegal transition (the registry calls this)."""
    if not can_transition(src, dst):
        raise ValueError(
            f"illegal lifecycle transition {src.value} -> {dst.value}; "
            f"legal forward targets: {[s.value for s in _FORWARD.get(src, set())]} "
            f"(plus 'retired' from any non-retired state)"
        )
