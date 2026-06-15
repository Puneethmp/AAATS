"""B1 — risk-managed cross-sectional momentum (candidate).

Hypothesis (see research/prereg/B1_xs_momentum.md): T2's failure was caused by its
risk CONSTRUCTION (net-beta, dollar sizing, no vol control, taker fees), not by the
predictive content of momentum ordering. B1 tests that by expressing a
risk-adjusted, reversal-skipped momentum signal as a dollar-neutral, beta-neutral,
vol-targeted, maker-executed long/short basket.

The strategy is THIN: it only produces the IR-momentum scores panel. All risk
construction (inverse-vol, beta-neutral, vol-target) lives in
quant.base.RiskManagedConstructor; execution in quant.base.MakerFillModel. This
module opens NO data and runs NO backtest on import — it only declares the signal.

⚠️ PRE-REGISTRATION GATE: FROZEN_PARAMS below are PENDING OPERATOR SIGN-OFF. Per the
program protocol they must be frozen + committed to origin/main BEFORE any real
U30 data is opened. Do not run the harness on real data until that is done.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant.base import (
    BaseStrategy,
    StrategySpec,
    PortfolioIntent,
    RiskControls,
    Scores,
    Lifecycle,
    REGISTRY,
)

# --- FROZEN-PENDING-SIGNOFF parameters (conventional values, not swept) ---
FROZEN_PARAMS: dict[str, Any] = {
    "formation_days": 28,  # Lf
    "skip_days": 7,  # Ls (reversal skip)
    "vol_lookback_days": 28,  # formation-window vol for IR + inverse-vol
    "rebalance_days": 30,  # monthly grid
    "long_fraction": 1 / 3,  # top tercile
    "short_fraction": 1 / 3,  # bottom tercile
    "beta_lookback_days": 30,
    "vol_target_annual": 0.15,
    "max_gross_leverage": 2.0,
    "max_weight_per_name": 0.15,
    "maker_fee_rate": -0.0002,
    "adverse_selection_bps": 3.0,
    "fill_prob_base": 0.8,
    "fill_prob_stress": 0.5,  # G7
    "seed": 7,
    "status": "DRAFT — PENDING OPERATOR SIGN-OFF; commit before opening data",
}

_EPS = 1e-12


def ir_momentum_panel(
    daily_close: pd.DataFrame, *, formation: int, skip: int
) -> pd.DataFrame:
    """Information-ratio momentum with a reversal skip, as a date x symbol panel.

    score(d) = formation_return / formation_vol, using only data strictly before d:
      formation_return = log P(d-skip) - log P(d-skip-formation)
      formation_vol    = std of daily log-returns over the formation window, lagged
                         by `skip` (so the most-recent `skip` days are excluded).
    Annualization cancels in the cross-sectional ranking, so it is omitted.
    """
    log_px = np.log(daily_close.where(daily_close > 0))
    formation_return = log_px.shift(skip) - log_px.shift(skip + formation)
    daily_logret = log_px.diff()
    formation_vol = (
        daily_logret.rolling(formation, min_periods=max(5, formation // 2))
        .std()
        .shift(skip)
    )
    return formation_return / (formation_vol + _EPS)


@REGISTRY.candidate
class B1CrossSectionalMomentum(BaseStrategy):
    spec = StrategySpec(
        id="b1_xs_momentum",
        family="cross_sectional_momentum",
        hypothesis="risk-managed (beta-neutral, vol-targeted, maker) XS momentum "
        "survives the rank-shuffle null where T2 (raw, taker, net-beta) did not",
        lifecycle=Lifecycle.RESEARCH,
        prereg_ref="research/prereg/B1_xs_momentum.md",
        tags=("perp", "u30", "monthly", "maker"),
        notes="Adjacent to falsified family T2; one honest shot. FAIL => XS momentum CLOSED.",
    )
    intent = PortfolioIntent(
        long_fraction=FROZEN_PARAMS["long_fraction"],
        short_fraction=FROZEN_PARAMS["short_fraction"],
        rebalance_days=FROZEN_PARAMS["rebalance_days"],
        risk=RiskControls(
            dollar_neutral=True,
            beta_neutral=True,
            beta_lookback_days=FROZEN_PARAMS["beta_lookback_days"],
            inverse_vol_weight=True,
            vol_target_annual=FROZEN_PARAMS["vol_target_annual"],
            vol_lookback_days=FROZEN_PARAMS["vol_lookback_days"],
            max_gross_leverage=FROZEN_PARAMS["max_gross_leverage"],
            max_weight_per_name=FROZEN_PARAMS["max_weight_per_name"],
        ),
    )

    def score(self, features: Any) -> Scores:
        """features: an object/dict carrying `daily_close` (days x symbols)."""
        daily_close = getattr(features, "daily_close", None)
        if daily_close is None and isinstance(features, dict):
            daily_close = features.get("daily_close")
        if daily_close is None:
            daily_close = features  # allow passing the DataFrame directly
        panel = ir_momentum_panel(
            daily_close,
            formation=FROZEN_PARAMS["formation_days"],
            skip=FROZEN_PARAMS["skip_days"],
        )
        return Scores(panel=panel, name="ir_momentum_28d_skip7")
