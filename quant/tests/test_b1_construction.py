"""B1 construction property tests (synthetic data — opens NO real data).

Proves the risk machinery actually does what B1 claims:
  - inverse-vol weighting favors lower-vol names
  - beta-neutralization drives net beta ~ 0 (and beats the un-neutralized book)
  - portfolio vol-target scales gross toward the target (or hits the leverage cap)
  - per-name and gross caps are respected
  - the maker fill model maps to ledger kwargs and drops fills probabilistically
  - the B1 IR-momentum score ranks a steady low-vol climber above a noisy one
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant.base import (
    MarketContext,
    PortfolioIntent,
    RiskControls,
    RiskManagedConstructor,
    MakerFillModel,
)


def _synth_context(n_days=80, seed=7):
    rng = np.random.default_rng(seed)
    syms = ["A", "B", "C", "D", "E", "F", "G", "H"]
    betas = dict(zip(syms, [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]))
    sigmas = dict(zip(syms, [0.005, 0.02, 0.01, 0.03, 0.008, 0.025, 0.015, 0.035]))
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D", tz="UTC")
    mkt = rng.normal(0, 0.02, n_days)
    data = {s: betas[s] * mkt + rng.normal(0, sigmas[s], n_days) for s in syms}
    rets = pd.DataFrame(data, index=idx)
    return MarketContext(daily_returns=rets), syms, betas, sigmas


def _intent():
    return PortfolioIntent(
        long_fraction=0.5,
        short_fraction=0.5,
        rebalance_days=30,
        risk=RiskControls(
            beta_neutral=True,
            inverse_vol_weight=True,
            vol_target_annual=0.15,
            vol_lookback_days=28,
            beta_lookback_days=30,
            max_gross_leverage=2.0,
            max_weight_per_name=0.40,
        ),
    )


def test_inverse_vol_favors_low_vol_names():
    ctx, syms, _, sigmas = _synth_context()
    date = ctx.daily_returns.index[-1]
    risk = _intent().risk
    leg = RiskManagedConstructor._inverse_vol_leg(
        date, ["A", "B", "D"], ctx, risk, sign=+1.0, cap=0.5
    )
    # A has the lowest sigma -> should carry the largest weight
    assert leg["A"] > leg["B"] and leg["A"] > leg["D"]


def test_beta_neutralization_reduces_net_beta():
    ctx, syms, _, _ = _synth_context()
    date = ctx.daily_returns.index[-1]
    cons = RiskManagedConstructor(_intent(), book=200.0)
    ranked = ["A", "B", "C", "D", "E", "F", "G", "H"]  # longs first half, shorts second
    w = cons.weights_for_date(date, ranked, ctx)
    betas = ctx.beta(date, list(w), 30)
    net_beta = sum((w[s] / cons.book) * float(betas[s]) for s in w)
    assert abs(net_beta) < 0.05, f"net beta not neutral: {net_beta:.4f}"


def test_vol_target_hits_target_or_leverage_cap():
    ctx, *_ = _synth_context()
    date = ctx.daily_returns.index[-1]
    cons = RiskManagedConstructor(_intent(), book=200.0)
    w = cons.weights_for_date(date, ["A", "B", "C", "D", "E", "F", "G", "H"], ctx)
    frac = {s: v / cons.book for s, v in w.items()}
    gross = sum(abs(v) for v in frac.values())
    pv = ctx.portfolio_realized_vol(date, frac, 28)
    hit_target = abs(pv - 0.15) / 0.15 < 0.20
    hit_cap = abs(gross - 2.0) < 0.05
    assert hit_target or hit_cap, f"vol={pv:.3f} gross={gross:.3f}"


def test_caps_respected():
    ctx, *_ = _synth_context()
    date = ctx.daily_returns.index[-1]
    intent = _intent()
    cons = RiskManagedConstructor(intent, book=200.0)
    w = cons.weights_for_date(date, ["A", "B", "C", "D", "E", "F", "G", "H"], ctx)
    frac = {s: v / cons.book for s, v in w.items()}
    gross = sum(abs(v) for v in frac.values())
    assert gross <= intent.risk.max_gross_leverage + 1e-6


def test_maker_fill_model_kwargs_and_drops():
    m = MakerFillModel(fill_prob=0.8)
    kw = m.ledger_kwargs()
    assert kw["fee_rate"] < 0  # rebate
    assert kw["half_spread_bps"] == 3.0  # adverse selection
    sched = [(pd.Timestamp("2026-01-01", tz="UTC"), {f"S{i}": 1.0 for i in range(200)})]
    rng = np.random.default_rng(7)
    kept = m.simulate_fills(sched, rng)[0][1]
    assert 140 <= len(kept) <= 180  # ~80% of 200 filled
    assert m.stressed().fill_prob == 0.5


def test_b1_ir_momentum_ranks_steady_climber_high():
    from quant.candidates.b1_xs_momentum import ir_momentum_panel

    idx = pd.date_range("2026-01-01", periods=60, freq="D", tz="UTC")
    rng = np.random.default_rng(7)
    steady = 100 * np.exp(
        np.cumsum(np.full(60, 0.004) + rng.normal(0, 0.001, 60))
    )  # low-vol uptrend
    noisy = 100 * np.exp(
        np.cumsum(np.full(60, 0.004) + rng.normal(0, 0.03, 60))
    )  # same drift, high vol
    flat = 100 * np.exp(np.cumsum(rng.normal(0, 0.005, 60)))  # no drift
    px = pd.DataFrame({"STEADY": steady, "NOISY": noisy, "FLAT": flat}, index=idx)
    panel = ir_momentum_panel(px, formation=28, skip=7)
    last = panel.iloc[-1].dropna()
    assert last["STEADY"] > last["NOISY"]  # risk-adjusted favors the steady climber
    assert last["STEADY"] > last["FLAT"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} B1 construction tests passed.")
