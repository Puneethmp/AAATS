"""Portfolio API — turns a scores panel into a rebalance schedule.

A PortfolioConstructor maps Scores -> the exact `schedule` shape that
tools/nautilus/basket_ledger.simulate_basket consumes:

    list[ (rebalance_ts, {symbol: signed_dollar_notional}) ]

DollarNeutralConstructor reproduces the existing T2-class construction (top/bottom
fraction, equal dollar) and is runnable today. RiskManagedConstructor is B1's
construction: inverse-vol legs, exact beta-neutralization, portfolio vol-target,
per-name + gross-leverage caps. Both receive the SAME optional MarketContext, and
the null control reuses the SAME constructor, so construction-driven Sharpe is
applied identically to real and shuffled signals (the anti-overfit invariant).

Neutrality note (made explicit, not hand-waved): you cannot be simultaneously
EXACT dollar-neutral and EXACT beta-neutral with only leg-level scalars unless the
long/short average betas already match. RiskManagedConstructor prioritizes exact
beta-neutrality and preserved gross, accepting a small, reported dollar residual
(see _beta_neutralize). This choice is pre-registered in the B1 spec.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .signal import Scores
from .strategy import PortfolioIntent

if TYPE_CHECKING:
    from .market import MarketContext

Schedule = list  # list[tuple[pd.Timestamp, dict[str, float]]]


class PortfolioConstructor(ABC):
    """Scores -> simulate_basket schedule. Subclass overrides weights_for_date."""

    def __init__(self, intent: PortfolioIntent, book: float = 200.0) -> None:
        self.intent = intent
        self.book = book

    def build_schedule(
        self,
        scores: Scores,
        context: "MarketContext | None" = None,
        membership: "dict | None" = None,
    ) -> Schedule:
        """Walk the rebalance grid and emit (ts, weights) per rebalance date."""
        panel = scores.panel
        dates = list(panel.index)[:: max(1, self.intent.rebalance_days)]
        schedule: Schedule = []
        for d in dates:
            ranked = scores.eligible(d)
            if membership is not None:
                allowed = set(membership.get(d, []))
                ranked = [s for s in ranked if s in allowed]
            if len(ranked) < 2:
                schedule.append((d, {}))  # nothing rankable -> liquidate
                continue
            schedule.append((d, self.weights_for_date(d, ranked, context)))
        return schedule

    @abstractmethod
    def weights_for_date(
        self, date, ranked: list[str], context: "MarketContext | None"
    ) -> "dict[str, float]":
        """Return {symbol: signed_dollar_notional} for one rebalance date."""
        raise NotImplementedError

    # --- shared helpers ---
    def _legs(self, ranked: list[str]) -> "tuple[list[str], list[str]]":
        n = len(ranked)
        q = max(1, int(round(n * self.intent.long_fraction)))
        qs = max(1, int(round(n * self.intent.short_fraction)))
        return ranked[:q], ranked[-qs:]


class DollarNeutralConstructor(PortfolioConstructor):
    """Equal-dollar top/bottom fraction, dollar-neutral. The T2-class baseline."""

    def weights_for_date(self, date, ranked, context=None) -> "dict[str, float]":
        longs, shorts = self._legs(ranked)
        leg_notional = self.book / 2.0  # gross = book; dollar-neutral
        w: dict[str, float] = {}
        if longs:
            per = leg_notional / len(longs)
            for s in longs:
                w[s] = +per
        if shorts:
            per = leg_notional / len(shorts)
            for s in shorts:
                w[s] = w.get(s, 0.0) - per
        return w


class RiskManagedConstructor(PortfolioConstructor):
    """B1 construction: inverse-vol legs + beta-neutral + portfolio vol-target.

    Requires a MarketContext. Works in weight-FRACTION space (each leg gross 0.5,
    book gross 1.0) until the vol-target scalar, then maps to signed dollar
    notional via `book`.
    """

    def weights_for_date(self, date, ranked, context) -> "dict[str, float]":
        if context is None:
            raise ValueError("RiskManagedConstructor requires a MarketContext")
        risk = self.intent.risk
        longs, shorts = self._legs(ranked)

        # 1) inverse-vol weights within each leg, gross 0.5 per leg, per-name capped
        cap = risk.max_weight_per_name * 0.5
        wl = self._inverse_vol_leg(date, longs, context, risk, sign=+1.0, cap=cap)
        ws = self._inverse_vol_leg(date, shorts, context, risk, sign=-1.0, cap=cap)
        w = {**wl, **{s: ws.get(s, 0.0) + wl.get(s, 0.0) for s in ws}}

        # 2) exact beta-neutralization (2-scalar solve, preserves gross ~1.0)
        if risk.beta_neutral:
            w = self._beta_neutralize(date, w, longs, shorts, context, risk)

        # 3) portfolio vol-target: scale gross to hit target, cap at max leverage
        if risk.vol_target_annual:
            pv = context.portfolio_realized_vol(date, w, risk.vol_lookback_days)
            g = (
                min(risk.max_gross_leverage, risk.vol_target_annual / pv)
                if pv > 0
                else 1.0
            )
            w = {s: v * g for s, v in w.items()}

        # 4) weight-fraction -> signed dollar notional
        return {s: v * self.book for s, v in w.items() if abs(v) > 1e-12}

    # --- internals ---
    @staticmethod
    def _inverse_vol_leg(date, names, context, risk, sign, cap):
        if not names:
            return {}
        vols = context.realized_vol(date, names, risk.vol_lookback_days)
        inv = {
            s: (1.0 / float(vols[s]) if vols.get(s, 0.0) and vols[s] > 0 else 0.0)
            for s in names
        }
        tot = sum(inv.values())
        if tot <= 0:  # vols unavailable -> equal weight fallback
            inv = {s: 1.0 for s in names}
            tot = float(len(names))
        # normalize leg to gross 0.5, then cap + renormalize (one pass)
        wt = {s: 0.5 * inv[s] / tot for s in names}
        wt = {s: min(v, cap) for s, v in wt.items()}
        tot2 = sum(wt.values())
        wt = {s: (0.5 * v / tot2 if tot2 > 0 else 0.0) for s, v in wt.items()}
        return {s: sign * v for s, v in wt.items()}

    @staticmethod
    def _beta_neutralize(date, w, longs, shorts, context, risk):
        all_names = list(set(longs) | set(shorts))
        betas = context.beta(date, all_names, risk.beta_lookback_days)
        bl = sum(w[s] * float(betas.get(s, 1.0)) for s in longs if s in w)  # >0 typ.
        bs = sum(w[s] * float(betas.get(s, 1.0)) for s in shorts if s in w)  # <0 typ.
        denom = bl - bs
        if abs(denom) < 1e-9:  # betas already matched -> nothing to do
            return w
        # solve  alpha*bl + beta*bs = 0,  alpha + beta = 2
        beta_s = 2.0 * bl / denom
        alpha_l = 2.0 - beta_s
        out = dict(w)
        for s in longs:
            if s in out:
                out[s] *= alpha_l
        for s in shorts:
            if s in out:
                out[s] *= beta_s
        return out
