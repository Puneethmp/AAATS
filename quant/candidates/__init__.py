"""quant.candidates — active strategy candidates, one self-contained module each.

A candidate module subclasses quant.base.BaseStrategy, declares its StrategySpec
+ PortfolioIntent, implements score(features) -> Scores, and registers via
@REGISTRY.candidate. The first planned candidate is B1 (risk-managed
cross-sectional momentum) — see quant/README.md. None exist yet (skeleton).
"""
