"""Strategy API — the thin contract a candidate implements.

A candidate subclasses BaseStrategy and implements ONE method:

    def score(self, features) -> Scores

It also declares static metadata (StrategySpec) and its construction intent
(PortfolioIntent + RiskControls). That is the entire authoring surface — ranking,
weighting, neutrality, vol-targeting, costs, walk-forward, null and gate are all
framework-owned and shared across every candidate, which is what kills the
C1/C3/C6 boilerplate duplication.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .lifecycle import Lifecycle
from .risk import RiskControls
from .signal import Scores


@dataclass(frozen=True)
class PortfolioIntent:
    """How the framework should turn this strategy's scores into a basket."""

    long_fraction: float = 1 / 3  # top tercile long
    short_fraction: float = 1 / 3  # bottom tercile short
    rebalance_days: int = 30  # monthly grid
    risk: RiskControls = field(default_factory=RiskControls)


@dataclass(frozen=True)
class StrategySpec:
    """Static identity + research metadata for a candidate."""

    id: str
    family: str  # e.g. "cross_sectional_momentum"
    hypothesis: str
    lifecycle: Lifecycle = Lifecycle.RESEARCH
    prereg_ref: str = ""  # path to committed pre-registration
    tags: tuple[str, ...] = ()
    notes: str = ""


class BaseStrategy(ABC):
    """Subclass this. Implement `score`. Declare `spec` and `intent`."""

    #: subclasses MUST set these (class attributes or set in __init__)
    spec: StrategySpec
    intent: PortfolioIntent = PortfolioIntent()

    @abstractmethod
    def score(self, features: Any) -> Scores:
        """Return a (date x symbol) Scores panel from a feature bundle.

        `features` is a lightweight container the data layer assembles
        (prices, funding, vols, membership). Kept as `Any` here so the base
        package stays import-light; candidates type it concretely.
        """
        raise NotImplementedError

    # --- convenience, not to be overridden ---
    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def lifecycle(self) -> Lifecycle:
        return self.spec.lifecycle

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"<{type(self).__name__} id={self.spec.id!r} state={self.lifecycle.value}>"
        )
