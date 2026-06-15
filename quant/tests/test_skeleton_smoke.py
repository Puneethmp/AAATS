"""Smoke test — proves the skeleton imports and the core contracts round-trip.

No heavy deps beyond pandas/numpy (already in the project). Run:
    python -m pytest quant/tests/test_skeleton_smoke.py
or standalone:
    python quant/tests/test_skeleton_smoke.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.base import (
    Scores,
    BaseStrategy,
    StrategySpec,
    PortfolioIntent,
    DollarNeutralConstructor,
    TakerExecution,
    RiskControls,
    Lifecycle,
    StrategyRegistry,
    PreRegistration,
    ValidationResult,
    can_transition,
)


def _toy_scores(n_days: int = 90, symbols=("A", "B", "C", "D", "E", "F")) -> Scores:
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D", tz="UTC")
    rng = np.random.default_rng(7)
    panel = pd.DataFrame(
        rng.standard_normal((n_days, len(symbols))), index=idx, columns=list(symbols)
    )
    return Scores(panel=panel, name="toy")


class _ToyStrategy(BaseStrategy):
    spec = StrategySpec(
        id="toy_xs", family="cross_sectional_momentum", hypothesis="toy"
    )
    intent = PortfolioIntent(
        risk=RiskControls(beta_neutral=True, vol_target_annual=0.15)
    )

    def __init__(self, scores: Scores) -> None:
        self._scores = scores

    def score(self, features) -> Scores:  # features unused in toy
        return self._scores


def test_scores_eligibility_ranks_high_to_low():
    s = _toy_scores()
    ranked = s.eligible(s.panel.index[0])
    row = s.panel.loc[s.panel.index[0]]
    assert ranked[0] == row.idxmax()
    assert ranked[-1] == row.idxmin()


def test_constructor_is_dollar_neutral():
    s = _toy_scores()
    cons = DollarNeutralConstructor(PortfolioIntent(rebalance_days=30), book=200.0)
    sched = cons.build_schedule(s)
    assert len(sched) == 3  # 90 days / 30
    _, weights = sched[0]
    net = sum(weights.values())
    gross = sum(abs(v) for v in weights.values())
    assert abs(net) < 1e-9  # dollar-neutral
    assert abs(gross - 200.0) < 1e-9  # gross == book


def test_execution_kwargs_match_ledger_signature():
    kw = TakerExecution().ledger_kwargs()
    assert set(kw) == {"fee_rate", "half_spread_bps", "impact_coef_bps"}


def test_lifecycle_topology():
    assert can_transition(Lifecycle.RESEARCH, Lifecycle.BACKTEST)
    assert not can_transition(Lifecycle.RESEARCH, Lifecycle.LIVE)
    assert can_transition(Lifecycle.PAPER, Lifecycle.RETIRED)  # demotion legal
    assert not can_transition(Lifecycle.RETIRED, Lifecycle.PAPER)


def test_registry_round_trip_and_gate_guard():
    reg = StrategyRegistry()
    reg.register(_ToyStrategy(_toy_scores()))
    assert reg.ids() == ["toy_xs"]
    assert reg.state_of("toy_xs") == Lifecycle.RESEARCH

    reg.attach_prereg(
        "toy_xs",
        PreRegistration(
            strategy_id="toy_xs",
            hypothesis="toy",
            mechanism="toy",
            universe="toy",
            horizon="monthly",
            null_model="rank-shuffle",
        ),
    )
    reg.record_validation(
        ValidationResult(strategy_id="toy_xs", stage="walkforward", passed=True)
    )
    # legal forward path
    reg.promote("toy_xs", Lifecycle.BACKTEST)
    reg.promote("toy_xs", Lifecycle.WALKFORWARD)
    reg.promote("toy_xs", Lifecycle.PAPER)
    assert reg.state_of("toy_xs") == Lifecycle.PAPER

    # illegal jump is refused
    try:
        reg2 = StrategyRegistry()
        reg2.register(_ToyStrategy(_toy_scores()))
        reg2.promote("toy_xs", Lifecycle.LIVE)  # RESEARCH -> LIVE illegal
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("illegal RESEARCH->LIVE transition was allowed")

    summ = reg.summary()
    assert summ[0]["state"] == "paper" and summ[0]["validations"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} smoke tests passed.")
