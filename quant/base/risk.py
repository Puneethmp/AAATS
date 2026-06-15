"""Risk API — declarative risk controls a strategy requests, the framework enforces.

A strategy does not implement risk logic; it declares the controls it wants via a
RiskControls record, and the PortfolioConstructor + ledger enforce them
identically for the real run AND the null (so vol-targeting can never be
mis-credited as signal). These defaults encode the program's standing rules:
dollar-neutral, beta-neutral, 15% portfolio vol-target, 2x gross cap, 15%/name
cap, and a -15% rolling-DD circuit-breaker.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskControls:
    dollar_neutral: bool = True
    beta_neutral: bool = False  # B1 sets True (30d regression beta)
    beta_lookback_days: int = 30
    inverse_vol_weight: bool = False  # B1 sets True (equal-risk legs)
    vol_target_annual: float | None = None  # e.g. 0.15; None disables
    vol_lookback_days: int = 30
    max_gross_leverage: float = 2.0
    max_weight_per_name: float = 0.15
    dd_circuit_breaker: float | None = -0.15  # halve gross if rolling DD breaches
    dd_lookback_days: int = 30

    def describe(self) -> str:
        bits = []
        if self.dollar_neutral:
            bits.append("dollar-neutral")
        if self.beta_neutral:
            bits.append(f"beta-neutral({self.beta_lookback_days}d)")
        if self.inverse_vol_weight:
            bits.append("inverse-vol")
        if self.vol_target_annual:
            bits.append(f"vol-target {self.vol_target_annual:.0%}")
        bits.append(f"<= {self.max_gross_leverage:g}x gross")
        bits.append(f"<= {self.max_weight_per_name:.0%}/name")
        if self.dd_circuit_breaker is not None:
            bits.append(f"DD breaker {self.dd_circuit_breaker:.0%}")
        return ", ".join(bits)
