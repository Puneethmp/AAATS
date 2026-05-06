"""
Transaction Cost Analysis (TCA)
=================================
Why this exists
---------------
Without measuring real transaction costs, you cannot improve execution.
Most retail and semi-institutional systems underestimate the true cost of
trading by 2–5x. This module provides the standard TCA decomposition used
by institutional trading desks.

Implementation Shortfall Decomposition (Perold 1988)
------------------------------------------------------
Total cost = Decision price impact + Execution cost + Opportunity cost

  IS = (Execution price - Decision price) * direction

Decomposed into:
  Market Impact   — Adverse price move caused by YOUR order
  Timing Cost     — Slippage due to price drift between decision and execution
  Spread Cost     — Half-spread paid on each trade (bid-ask)
  Opportunity Cost— Value of unexecuted order (if partially filled)

Benchmark Comparisons
---------------------
  VWAP slippage  — Execution price vs. VWAP over the participation window
  TWAP slippage  — Execution price vs. TWAP (time-weighted average)
  Arrival price  — Execution price vs. mid-price at order arrival

Market Impact Model (Square-Root Law)
--------------------------------------
  Impact (bps) = eta * sigma * sqrt(participation_rate) * 10,000

  where:
    eta              ≈ 0.1 (market impact coefficient, calibrate to your market)
    sigma            = daily volatility of the asset (from returns)
    participation    = order size / ADV (average daily volume)

  This model is supported by Almgren et al. (2005), Grinold & Kahn,
  and is used by most institutional execution desks.

Usage
-----
  from research.tca import TCAAnalyzer, Order

  analyzer = TCAAnalyzer()
  order = Order(
      symbol='BTC/USDT', side='buy', quantity=1.0,
      decision_price=50000.0, execution_price=50250.0,
      vwap=50100.0, arrival_mid=50050.0,
      adv=1000.0, sigma=0.02
  )
  result = analyzer.analyze(order)
  print(result)

  # Batch analysis from trade log
  report = analyzer.analyze_batch(trade_log_df)
  print(report.summary())
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd

__all__ = ["Order", "TCAResult", "TCAAnalyzer", "TCAReport"]


# ---------------------------------------------------------------------------
# Order and TCAResult dataclasses
# ---------------------------------------------------------------------------
@dataclass
class Order:
    """Represents a single order for TCA analysis."""
    symbol: str
    side: str                        # 'buy' or 'sell'
    quantity: float                  # shares / contracts / coins
    decision_price: float            # mid-price at decision time
    execution_price: float           # actual fill price (average)
    vwap: float | None = None        # VWAP over execution window
    twap: float | None = None        # TWAP over execution window
    arrival_mid: float | None = None # mid-price at order arrival
    adv: float | None = None         # average daily volume (same units as qty)
    sigma: float | None = None       # daily volatility (decimal, e.g. 0.02 = 2%)
    spread_bps: float | None = None  # bid-ask spread in basis points
    timestamp: pd.Timestamp | None = None
    execution_time_bars: int = 1     # how many bars to fill the order

    @property
    def direction(self) -> int:
        return 1 if self.side.lower() == "buy" else -1

    @property
    def participation_rate(self) -> float | None:
        if self.adv and self.adv > 0:
            return min(self.quantity / self.adv, 1.0)
        return None


@dataclass
class TCAResult:
    """TCA results for a single order."""
    symbol: str
    side: str
    quantity: float
    decision_price: float
    execution_price: float

    # Cost components (all in bps, positive = cost, negative = saving)
    implementation_shortfall_bps: float = 0.0
    vwap_slippage_bps: float | None = None
    twap_slippage_bps: float | None = None
    arrival_slippage_bps: float | None = None
    estimated_spread_cost_bps: float | None = None
    estimated_market_impact_bps: float | None = None
    timing_cost_bps: float | None = None

    # Summary
    total_cost_bps: float = 0.0
    total_cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# TCA Analyzer
# ---------------------------------------------------------------------------
class TCAAnalyzer:
    """
    Transaction Cost Analyzer.

    Parameters
    ----------
    impact_eta      Market impact coefficient in square-root model (default 0.1).
    """

    def __init__(self, impact_eta: float = 0.1):
        self.impact_eta = impact_eta

    # ------------------------------------------------------------------
    def analyze(self, order: Order) -> TCAResult:
        """Analyze a single order and return a TCAResult."""
        d = order.direction
        ep = order.execution_price
        dp = order.decision_price

        # Implementation Shortfall (IS) = total cost vs. decision price
        if dp > 0:
            is_bps = (ep - dp) * d / dp * 1e4
        else:
            is_bps = 0.0

        result = TCAResult(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            decision_price=dp,
            execution_price=ep,
            implementation_shortfall_bps=round(is_bps, 2),
        )

        # VWAP slippage
        if order.vwap and order.vwap > 0:
            result.vwap_slippage_bps = round((ep - order.vwap) * d / order.vwap * 1e4, 2)

        # TWAP slippage
        if order.twap and order.twap > 0:
            result.twap_slippage_bps = round((ep - order.twap) * d / order.twap * 1e4, 2)

        # Arrival price slippage
        if order.arrival_mid and order.arrival_mid > 0:
            result.arrival_slippage_bps = round(
                (ep - order.arrival_mid) * d / order.arrival_mid * 1e4, 2
            )

        # Estimated spread cost
        if order.spread_bps is not None:
            result.estimated_spread_cost_bps = round(order.spread_bps / 2, 2)
        else:
            # Estimate: typical spread for the decision-price level
            if dp > 10_000:
                spread_est = 1.0   # BTC-like: ~1 bps
            elif dp > 100:
                spread_est = 3.0   # equity-like
            else:
                spread_est = 5.0   # low-price asset
            result.estimated_spread_cost_bps = round(spread_est / 2, 2)

        # Market impact (square-root model)
        if order.sigma and order.participation_rate:
            impact = (
                self.impact_eta
                * order.sigma
                * np.sqrt(order.participation_rate)
                * 1e4
            )
            result.estimated_market_impact_bps = round(impact, 2)

        # Timing cost = IS - spread - impact (residual)
        if (result.estimated_spread_cost_bps is not None and
                result.estimated_market_impact_bps is not None):
            result.timing_cost_bps = round(
                is_bps
                - result.estimated_spread_cost_bps
                - result.estimated_market_impact_bps,
                2
            )

        # Total cost
        cost_components = [
            c for c in [
                result.estimated_spread_cost_bps,
                result.estimated_market_impact_bps,
                max(result.timing_cost_bps or 0, 0),
            ] if c is not None
        ]
        result.total_cost_bps = round(sum(cost_components), 2)
        result.total_cost_usd = round(
            result.total_cost_bps / 1e4 * ep * order.quantity, 4
        )

        return result

    # ------------------------------------------------------------------
    def analyze_batch(self, df: pd.DataFrame) -> "TCAReport":
        """
        Analyze a batch of trades from a DataFrame.

        Expected columns: symbol, side, quantity, decision_price,
        execution_price, vwap (optional), adv (optional), sigma (optional).
        """
        results = []
        for _, row in df.iterrows():
            try:
                order = Order(
                    symbol=str(row.get("symbol", "UNK")),
                    side=str(row.get("side", "buy")),
                    quantity=float(row.get("quantity", 1.0)),
                    decision_price=float(row.get("decision_price", row.get("entry_price", 0.0))),
                    execution_price=float(row.get("execution_price", row.get("exit_price", 0.0))),
                    vwap=float(row["vwap"]) if "vwap" in row and not pd.isna(row["vwap"]) else None,
                    adv=float(row["adv"]) if "adv" in row and not pd.isna(row["adv"]) else None,
                    sigma=float(row["sigma"]) if "sigma" in row and not pd.isna(row["sigma"]) else None,
                    spread_bps=float(row["spread_bps"]) if "spread_bps" in row else None,
                    timestamp=row.get("timestamp") or row.get("entry_date"),
                )
                results.append(self.analyze(order))
            except Exception as e:
                warnings.warn(f"Could not analyze row: {e}", stacklevel=2)

        return TCAReport(results)

    # ------------------------------------------------------------------
    def estimate_pre_trade(
        self,
        symbol: str,
        side: str,
        quantity: float,
        current_price: float,
        sigma: float,
        adv: float,
        spread_bps: float | None = None,
    ) -> dict:
        """
        Pre-trade cost estimate before order execution.

        Returns expected total cost in bps and USD.
        """
        participation = min(quantity / max(adv, 1e-9), 1.0)
        impact_bps = self.impact_eta * sigma * np.sqrt(participation) * 1e4
        spread_cost = (spread_bps or 5.0) / 2
        total_bps = impact_bps + spread_cost
        total_usd = total_bps / 1e4 * current_price * quantity

        return {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "current_price": current_price,
            "participation_rate_pct": round(participation * 100, 3),
            "estimated_spread_cost_bps": round(spread_cost, 2),
            "estimated_market_impact_bps": round(impact_bps, 2),
            "estimated_total_cost_bps": round(total_bps, 2),
            "estimated_total_cost_usd": round(total_usd, 4),
            "breakeven_edge_bps": round(total_bps * 2, 2),  # need 2x cost as alpha
            "advice": (
                "LOW COST — proceed" if total_bps < 5
                else "MODERATE COST — consider timing" if total_bps < 20
                else "HIGH COST — reduce size or wait for better liquidity"
            ),
        }


# ---------------------------------------------------------------------------
# TCA Report (batch summary)
# ---------------------------------------------------------------------------
class TCAReport:
    """Aggregate TCA results across a batch of trades."""

    def __init__(self, results: list[TCAResult]):
        self.results = results
        self._df = pd.DataFrame([r.to_dict() for r in results]) if results else pd.DataFrame()

    def summary(self) -> dict:
        if self._df.empty:
            return {"error": "No trade results to summarise."}
        df = self._df
        return {
            "n_trades": len(df),
            "avg_is_bps": round(float(df["implementation_shortfall_bps"].mean()), 3),
            "median_is_bps": round(float(df["implementation_shortfall_bps"].median()), 3),
            "avg_total_cost_bps": round(float(df["total_cost_bps"].mean()), 3),
            "total_cost_usd": round(float(df["total_cost_usd"].sum()), 2),
            "avg_spread_cost_bps": round(float(df["estimated_spread_cost_bps"].mean()), 3)
            if "estimated_spread_cost_bps" in df.columns else None,
            "avg_impact_bps": round(float(df["estimated_market_impact_bps"].mean()), 3)
            if "estimated_market_impact_bps" in df.columns else None,
            "pct_positive_is": round(float((df["implementation_shortfall_bps"] > 0).mean() * 100), 1),
            "worst_is_bps": round(float(df["implementation_shortfall_bps"].max()), 2),
            "best_is_bps": round(float(df["implementation_shortfall_bps"].min()), 2),
            "by_symbol": df.groupby("symbol")["implementation_shortfall_bps"].mean().round(3).to_dict()
            if "symbol" in df.columns else {},
            "by_side": df.groupby("side")["implementation_shortfall_bps"].mean().round(3).to_dict()
            if "side" in df.columns else {},
        }

    def to_dataframe(self) -> pd.DataFrame:
        return self._df.copy()
