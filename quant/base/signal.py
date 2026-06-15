"""Signal API — the one thing a strategy author produces.

A strategy emits a *scores panel*: a (date x symbol) table of real-valued
cross-sectional scores. HIGH score = strongest long conviction, LOW = strongest
short. The framework converts ranks->weights downstream; the strategy never sees
fees, sizing, or execution.

This deliberately mirrors what tools/nautilus/xsect_signals.py already produces
(e.g. momentum_panel -> a date x symbol DataFrame), so existing signal builders
drop in unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # keep base import-light; pandas only needed at runtime
    import pandas as pd


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True)
class Scores:
    """A cross-sectional scores panel.

    Parameters
    ----------
    panel : pandas.DataFrame
        Index = rebalance/observation dates (UTC midnight), columns = symbols,
        values = real-valued scores. NaN where a name is ineligible that date
        (insufficient history, data gap) — the constructor skips NaNs.
    name : str
        Human label for the signal (e.g. "ir_momentum_28d_skip7").
    """

    panel: "pd.DataFrame"
    name: str = "scores"

    def eligible(self, date) -> list[str]:
        """Symbols with a non-NaN score on `date`, ranked HIGH->LOW."""
        row = self.panel.loc[date].dropna()
        return list(row.sort_values(ascending=False).index)

    def __post_init__(self) -> None:
        # Fail fast on the shape mistake that silently breaks ranking.
        if self.panel.ndim != 2:
            raise ValueError("Scores.panel must be a 2-D (date x symbol) DataFrame")
