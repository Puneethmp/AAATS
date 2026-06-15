"""Execution API — maps an execution model to simulate_basket cost kwargs.

The ledger (basket_ledger.simulate_basket) prices costs on |Δnotional| turnover via
fee_rate (taker), half_spread_bps and impact_coef_bps. An ExecutionModel packages a
costing assumption into those kwargs so research, paper and the thin live executor
price fills identically.

  TakerExecution  — flat taker fee + optional spread/impact. Matches today's ledger.
  MakerFillModel  — B1's execution: a maker REBATE (negative fee), an adverse-
                    selection haircut, and a probabilistic fill transform on the
                    schedule. This is the most likely place B1 dies even if the
                    signal is real, so it is explicit and testable, not hidden.

Mapping choice (documented): simulate_basket has no native probabilistic-fill or
adverse-selection term, so MakerFillModel expresses them as
  (a) fee_rate = maker_fee_rate (negative = rebate),
  (b) half_spread_bps = adverse_selection_bps  (effective haircut on FILLED turnover),
  (c) a schedule transform that drops each name with prob (1 - fill_prob): unfilled
      => you stay flat for that name that period (you do NOT chase). Gross shrinks
      accordingly, which is the realistic consequence of a missed maker fill.
The null run applies the IDENTICAL transform with the IDENTICAL seed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

Schedule = list  # list[tuple[ts, {symbol: signed_dollar_notional}]]


@dataclass(frozen=True)
class ExecutionModel(ABC):
    @abstractmethod
    def ledger_kwargs(self) -> dict:
        """kwargs to splat into simulate_basket(...)."""
        raise NotImplementedError

    def simulate_fills(
        self, schedule: Schedule, rng: "np.random.Generator | None" = None
    ) -> Schedule:
        """Default: deterministic full fills (taker). Subclasses may override."""
        return schedule


@dataclass(frozen=True)
class TakerExecution(ExecutionModel):
    """Flat taker fee + optional spread/impact. Matches the current ledger."""

    fee_rate: float = 0.0005  # 5 bps/side taker
    half_spread_bps: float = 0.0
    impact_coef_bps: float = 0.0

    def ledger_kwargs(self) -> dict:
        return {
            "fee_rate": self.fee_rate,
            "half_spread_bps": self.half_spread_bps,
            "impact_coef_bps": self.impact_coef_bps,
        }


@dataclass(frozen=True)
class MakerFillModel(ExecutionModel):
    """Maker rebate + adverse-selection haircut + probabilistic fills (B1)."""

    maker_fee_rate: float = -0.0002  # -2 bps rebate-inclusive VIP-0 maker
    adverse_selection_bps: float = (
        3.0  # effective half-spread haircut on filled turnover
    )
    fill_prob: float = 0.8  # base case; G7 stress = 0.5
    impact_coef_bps: float = 0.0  # maker provides liquidity -> no taker impact

    def ledger_kwargs(self) -> dict:
        return {
            "fee_rate": self.maker_fee_rate,
            "half_spread_bps": self.adverse_selection_bps,
            "impact_coef_bps": self.impact_coef_bps,
        }

    def simulate_fills(self, schedule: Schedule, rng=None) -> Schedule:
        """Drop each name with prob (1 - fill_prob): unfilled => flat that period."""
        if rng is None:
            import numpy as np

            rng = np.random.default_rng(7)
        out: Schedule = []
        for ts, weights in schedule:
            kept = {s: v for s, v in weights.items() if rng.random() < self.fill_prob}
            out.append((ts, kept))
        return out

    def stressed(self, fill_prob: float = 0.5) -> "MakerFillModel":
        """Return the G7 stress variant (lower fill probability)."""
        return MakerFillModel(
            maker_fee_rate=self.maker_fee_rate,
            adverse_selection_bps=self.adverse_selection_bps,
            fill_prob=fill_prob,
            impact_coef_bps=self.impact_coef_bps,
        )
