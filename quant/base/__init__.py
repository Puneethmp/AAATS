"""quant.base — the standard contracts every candidate plugs into.

Public surface (import from quant.base):
  Signal API     : Side, Scores
  Market         : MarketContext
  Strategy API   : BaseStrategy, StrategySpec, PortfolioIntent
  Portfolio API  : PortfolioConstructor, DollarNeutralConstructor, RiskManagedConstructor
  Execution API  : ExecutionModel, TakerExecution, MakerFillModel
  Risk API       : RiskControls
  Lifecycle      : Lifecycle, can_transition, assert_transition
  Registry       : StrategyRegistry, REGISTRY
  Metadata       : PreRegistration, ValidationResult
"""

from .signal import Side, Scores
from .market import MarketContext
from .strategy import BaseStrategy, StrategySpec, PortfolioIntent
from .portfolio import (
    PortfolioConstructor,
    DollarNeutralConstructor,
    RiskManagedConstructor,
)
from .execution import ExecutionModel, TakerExecution, MakerFillModel
from .risk import RiskControls
from .lifecycle import Lifecycle, can_transition, assert_transition
from .registry import StrategyRegistry, REGISTRY
from .metadata import PreRegistration, ValidationResult

__all__ = [
    "Side",
    "Scores",
    "MarketContext",
    "BaseStrategy",
    "StrategySpec",
    "PortfolioIntent",
    "PortfolioConstructor",
    "DollarNeutralConstructor",
    "RiskManagedConstructor",
    "ExecutionModel",
    "TakerExecution",
    "MakerFillModel",
    "RiskControls",
    "Lifecycle",
    "can_transition",
    "assert_transition",
    "StrategyRegistry",
    "REGISTRY",
    "PreRegistration",
    "ValidationResult",
]
