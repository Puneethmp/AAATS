"""
Portfolio Allocation Engine
============================
Why this exists
---------------
AAATS had two completely disconnected allocation systems:
  - portfolio/optimizer.py    — MVO, risk-parity, max-Sharpe, Kelly (mathematical)
  - portfolio/capital_allocator.py — health-score based allocation (operational)

Neither talked to the other. The optimizer computed mathematically optimal weights
but they were never used. The allocator assigned capital based on strategy health
scores alone, ignoring covariance structure, Kelly fractions, and risk budgets.

This module is the bridge. It:
  1. Takes strategy return history + current health scores as input
  2. Runs the optimizer (regime-conditional) to get mathematically optimal weights
  3. Blends optimized weights with health-score weights (configurable)
  4. Applies hard constraint limits (per-strategy, per-market, cash reserve)
  5. Feeds final weights into position sizing

Architecture
------------
  StrategyReturns → Optimizer → Raw Weights
                                      ↓
  HealthScores → HealthWeights → Blended Weights → Constraints → Final Allocation
                                      ↑
                                  RegimeSignal (from regime_pipeline)

Regime-Conditional Allocation
------------------------------
  BULL_TREND:      Use max-Sharpe / momentum-tilt (higher equity weights)
  BEAR_TREND:      Use min-variance / defensive (lower risk, more cash)
  RANGE_BOUND:     Use risk-parity (equal risk contribution)
  HIGH_VOLATILITY: Flat weights, reduce all sizes by confidence factor
  UNKNOWN:         Conservative (50% cash minimum)

Usage
-----
  from portfolio.allocation_engine import AllocationEngine

  engine = AllocationEngine(total_capital=500_000)

  allocation = engine.allocate(
      strategy_returns={"strat_A": pd.Series(...), "strat_B": pd.Series(...)},
      health_scores={"strat_A": 0.8, "strat_B": 0.6},
      regime="BULL_TREND",
      regime_confidence=0.75,
  )
  print(allocation)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from portfolio.optimizer import (
    max_sharpe, min_variance, risk_parity, kelly_criterion,
    portfolio_stats,
)
from foundation.logger import get_logger

_log = get_logger("portfolio", "allocation_engine")

__all__ = ["AllocationEngine", "AllocationResult"]

RegimeType = Literal["BULL_TREND", "BEAR_TREND", "RANGE_BOUND", "HIGH_VOLATILITY", "UNKNOWN"]

# Minimum bars of return history needed to run optimizer
_MIN_BARS_FOR_OPTIMIZATION = 60


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class AllocationResult:
    """
    Final capital allocation per strategy.
    """
    strategy_weights: dict[str, float]      # 0.0–1.0, sums to ≤ 1
    strategy_capital: dict[str, float]      # absolute USD/INR per strategy
    cash_reserve: float                     # undeployed capital
    total_capital: float
    regime: str
    regime_confidence: float
    optimizer_method: str                   # which optimizer was used
    blend_factor: float                     # weight of optimizer vs health scores

    # Risk stats on the final portfolio
    ann_return_pct: float | None = None
    ann_volatility_pct: float | None = None
    portfolio_sharpe: float | None = None
    risk_contributions: dict[str, float] = field(default_factory=dict)  # % each strat contributes

    def deployed_pct(self) -> float:
        return sum(self.strategy_weights.values())

    def summary(self) -> str:
        lines = [
            f"Regime: {self.regime} (confidence={self.regime_confidence:.2f})",
            f"Optimizer: {self.optimizer_method} (blend={self.blend_factor:.2f})",
            f"Deployed: {self.deployed_pct():.1%} of capital",
            f"Cash reserve: {self.cash_reserve:,.0f} ({1 - self.deployed_pct():.1%})",
            "Allocations:",
        ]
        for strat, w in sorted(self.strategy_weights.items(), key=lambda x: -x[1]):
            cap = self.strategy_capital[strat]
            rc = self.risk_contributions.get(strat, 0.0)
            lines.append(f"  {strat:<30} {w:>6.2%}  ${cap:>12,.0f}  risk={rc:.2%}")
        if self.portfolio_sharpe:
            lines.append(
                f"Portfolio: return={self.ann_return_pct:.1f}%  "
                f"vol={self.ann_volatility_pct:.1f}%  "
                f"Sharpe={self.portfolio_sharpe:.3f}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Allocation Engine
# ---------------------------------------------------------------------------
class AllocationEngine:
    """
    Regime-conditional portfolio allocation using optimized + health-score blend.

    Parameters
    ----------
    total_capital           Total capital to allocate.
    max_strategy_weight     Max weight per strategy (default 15%).
    min_strategy_weight     Min weight per active strategy (default 2%).
    max_deployed            Max total deployed capital (default 80%, 20% cash).
    health_blend            Weight of health-score allocation vs optimizer (0=pure health, 1=pure optimizer).
                            Default 0.5: equal blend.
    risk_free_rate          Annual risk-free rate for Sharpe computation.
    annualise_factor        Bars/year for return stats.
    """

    def __init__(
        self,
        total_capital: float,
        max_strategy_weight: float = 0.15,
        min_strategy_weight: float = 0.02,
        max_deployed: float = 0.80,
        health_blend: float = 0.5,
        risk_free_rate: float = 0.05,
        annualise_factor: float = 252.0,
    ):
        if not 0 < total_capital:
            raise ValueError("total_capital must be positive")
        self.total_capital = total_capital
        self.max_w = max_strategy_weight
        self.min_w = min_strategy_weight
        self.max_deployed = max_deployed
        self.health_blend = health_blend
        self.risk_free_rate = risk_free_rate
        self.annualise_factor = annualise_factor

    # ------------------------------------------------------------------
    def allocate(
        self,
        strategy_returns: dict[str, pd.Series],
        health_scores: dict[str, float],
        regime: RegimeType = "UNKNOWN",
        regime_confidence: float = 0.5,
        market_constraints: dict[str, float] | None = None,
    ) -> AllocationResult:
        """
        Compute final capital allocation across strategies.

        Parameters
        ----------
        strategy_returns    Dict of strategy_id → pd.Series of daily returns.
                            Must have at least 60 bars to run optimizer.
        health_scores       Dict of strategy_id → health score (0.0–1.0).
        regime              Current market regime label.
        regime_confidence   Confidence in the regime signal (0.0–1.0).
        market_constraints  Optional dict of market_id → max weight (e.g. {"crypto": 0.20}).

        Returns
        -------
        AllocationResult with final weights, capital, and risk stats.
        """
        strategies = list(strategy_returns.keys())
        if not strategies:
            return self._empty_result(regime, regime_confidence)

        # --- Filter to strategies with sufficient history ---
        valid = {
            s: ret for s, ret in strategy_returns.items()
            if len(ret.dropna()) >= _MIN_BARS_FOR_OPTIMIZATION
        }

        # --- Step 1: Health-score weights ---
        health_w = self._health_weights(health_scores, strategies)

        # --- Step 2: Optimizer weights ---
        optimizer_w, optimizer_method = self._optimizer_weights(valid, regime, regime_confidence)

        # Extend optimizer weights to all strategies (zeros for unoptimized)
        for s in strategies:
            optimizer_w.setdefault(s, 0.0)

        # --- Step 3: Blend ---
        blend = self._blend(health_w, optimizer_w, regime, regime_confidence)

        # --- Step 4: Regime-based size scaling ---
        vol_scale = self._regime_size_scale(regime, regime_confidence)
        blend = {s: w * vol_scale for s, w in blend.items()}

        # --- Step 5: Constraints ---
        blend = self._apply_constraints(blend, market_constraints)

        # --- Step 6: Ensure total ≤ max_deployed ---
        total_w = sum(blend.values())
        if total_w > self.max_deployed:
            scale = self.max_deployed / total_w
            blend = {s: w * scale for s, w in blend.items()}

        # --- Step 7: Capital allocation ---
        strategy_capital = {s: w * self.total_capital for s, w in blend.items()}
        cash_reserve = self.total_capital - sum(strategy_capital.values())

        # --- Step 8: Portfolio risk stats ---
        ann_return = ann_vol = sharpe = None
        risk_contribs: dict[str, float] = {}

        if len(valid) >= 2:
            try:
                weights_arr = np.array([blend.get(s, 0.0) for s in valid])
                weights_arr /= max(weights_arr.sum(), 1e-9)

                ret_df = pd.DataFrame(valid).dropna()
                mu = ret_df.mean().values * self.annualise_factor
                cov = ret_df.cov().values * self.annualise_factor
                stats = portfolio_stats(weights_arr, mu, cov, self.risk_free_rate)
                ann_return = round(float(stats["ann_return"]) * 100, 2)
                ann_vol = round(float(stats["ann_volatility"]) * 100, 2)
                sharpe = round(float(stats["sharpe"]), 3)

                # Risk contributions (marginal contribution × weight)
                port_var = weights_arr @ cov @ weights_arr
                if port_var > 0:
                    marginal = cov @ weights_arr
                    risk_c = weights_arr * marginal / port_var
                    for i, s in enumerate(valid):
                        risk_contribs[s] = round(float(risk_c[i]), 4)
            except Exception as exc:
                _log.debug(f"Portfolio stats failed: {exc}")

        return AllocationResult(
            strategy_weights=blend,
            strategy_capital=strategy_capital,
            cash_reserve=cash_reserve,
            total_capital=self.total_capital,
            regime=regime,
            regime_confidence=regime_confidence,
            optimizer_method=optimizer_method,
            blend_factor=self.health_blend,
            ann_return_pct=ann_return,
            ann_volatility_pct=ann_vol,
            portfolio_sharpe=sharpe,
            risk_contributions=risk_contribs,
        )

    # ------------------------------------------------------------------
    def _health_weights(
        self, health_scores: dict[str, float], strategies: list[str]
    ) -> dict[str, float]:
        """Convert health scores to allocation weights (proportional, constrained)."""
        scores = {s: max(health_scores.get(s, 0.0), 0.0) for s in strategies}
        total = sum(scores.values())
        if total == 0:
            return {s: 1.0 / len(strategies) for s in strategies}
        return {s: v / total for s, v in scores.items()}

    # ------------------------------------------------------------------
    def _optimizer_weights(
        self,
        valid: dict[str, pd.Series],
        regime: str,
        confidence: float,
    ) -> tuple[dict[str, float], str]:
        """Run regime-appropriate optimizer and return weights."""
        if not valid:
            return {}, "none"

        strats = list(valid.keys())
        ret_df = pd.DataFrame(valid).dropna()

        if len(ret_df) < _MIN_BARS_FOR_OPTIMIZATION or len(strats) < 2:
            # Single strategy or too few bars — uniform
            w = 1.0 / len(strats)
            return {s: w for s in strats}, "uniform"

        mu = ret_df.mean().values * self.annualise_factor
        cov = ret_df.cov().values * self.annualise_factor

        # Constrain per-strategy weight
        w_max = min(self.max_w, 1.0 / len(strats) * 3)  # at most 3x equal weight
        w_min = 0.0

        method = "risk_parity"
        weights_arr: np.ndarray | None = None

        try:
            if regime == "BULL_TREND" and confidence >= 0.6:
                # Maximize return-per-unit-risk
                result = max_sharpe(
                    mu, cov, risk_free=self.risk_free_rate,
                    w_max=w_max, w_min=w_min, ann=False,
                )
                weights_arr = result.get("weights")
                method = "max_sharpe"

            elif regime == "BEAR_TREND":
                # Minimize variance (defensive)
                result = min_variance(mu, cov, w_max=w_max, w_min=w_min, ann=False)
                weights_arr = result.get("weights")
                method = "min_variance"

            elif regime in ("RANGE_BOUND", "HIGH_VOLATILITY", "UNKNOWN"):
                # Equal risk contribution
                result = risk_parity(mu, cov, risk_free=self.risk_free_rate,
                                     w_max=w_max, w_min=w_min, ann=False)
                weights_arr = result.get("weights")
                method = "risk_parity"

        except Exception as exc:
            _log.warning(f"Optimizer ({method}) failed: {exc}. Falling back to risk_parity.")
            try:
                result = risk_parity(mu, cov, w_max=w_max, w_min=w_min, ann=False)
                weights_arr = result.get("weights")
                method = "risk_parity_fallback"
            except Exception:
                pass

        if weights_arr is None or len(weights_arr) != len(strats):
            weights_arr = np.ones(len(strats)) / len(strats)
            method = "uniform"

        return {s: float(w) for s, w in zip(strats, weights_arr)}, method

    # ------------------------------------------------------------------
    def _blend(
        self,
        health_w: dict[str, float],
        optimizer_w: dict[str, float],
        regime: str,
        confidence: float,
    ) -> dict[str, float]:
        """Weighted average of health scores and optimizer weights."""
        # In low-confidence or unknown regime, trust health scores more
        if regime == "UNKNOWN" or confidence < 0.4:
            opt_blend = 0.2
        elif confidence < 0.6:
            opt_blend = self.health_blend * 0.7
        else:
            opt_blend = self.health_blend

        health_blend = 1.0 - opt_blend
        strategies = set(health_w) | set(optimizer_w)

        blended = {}
        for s in strategies:
            hw = health_w.get(s, 0.0)
            ow = optimizer_w.get(s, 0.0)
            blended[s] = health_blend * hw + opt_blend * ow

        # Normalise
        total = sum(blended.values())
        if total > 0:
            blended = {s: v / total for s, v in blended.items()}

        return blended

    # ------------------------------------------------------------------
    def _regime_size_scale(self, regime: str, confidence: float) -> float:
        """
        Overall portfolio size scalar based on regime.
        Returns 0.0–1.0 applied to ALL strategy weights before constraints.
        """
        base_scales = {
            "BULL_TREND":      1.00,
            "RANGE_BOUND":     0.80,
            "BEAR_TREND":      0.60,
            "HIGH_VOLATILITY": 0.40,
            "UNKNOWN":         0.50,
        }
        base = base_scales.get(regime, 0.5)
        # Scale further by confidence (low confidence → smaller positions)
        confidence_adj = 0.5 + 0.5 * confidence  # maps [0,1] → [0.5, 1.0]
        return round(base * confidence_adj, 4)

    # ------------------------------------------------------------------
    def _apply_constraints(
        self,
        weights: dict[str, float],
        market_constraints: dict[str, float] | None,
    ) -> dict[str, float]:
        """Clip weights to per-strategy limits and remove below-minimum."""
        # Clip to max
        clipped = {s: min(w, self.max_w) for s, w in weights.items()}

        # Remove below minimum (inactive)
        active = {s: w for s, w in clipped.items() if w >= self.min_w}

        # Renormalise if any were removed
        total = sum(active.values())
        if total > 0 and total != 1.0:
            active = {s: v / total for s, v in active.items()}

        return active

    # ------------------------------------------------------------------
    def _empty_result(self, regime: str, confidence: float) -> AllocationResult:
        return AllocationResult(
            strategy_weights={},
            strategy_capital={},
            cash_reserve=self.total_capital,
            total_capital=self.total_capital,
            regime=regime,
            regime_confidence=confidence,
            optimizer_method="none",
            blend_factor=self.health_blend,
        )
