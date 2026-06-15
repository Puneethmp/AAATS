# quant/ — next-generation AAATS strategy framework (skeleton)

**Status:** skeleton, 2026-06-14. Imports clean, 5/5 smoke tests pass. Nothing
in the live trading path is touched by this package. The running paper bot is
unaffected.

## Why this exists

The 2026-06-14 architecture review found AAATS was built backwards: heavy
execution/dashboard infrastructure wrapped around a research program that never
produced a validated edge. The one component that always did its job is the
null-controlled walk-forward harness (`tools/nautilus/*` + `tools/graduation/gate.py`).

`quant/` is the thin, standard set of contracts that wraps that harness so a new
strategy candidate is a ~100-line module instead of a fork of the 2,351-line
runner. It eliminates the C1/C3/C6 boilerplate duplication by moving all
non-signal logic into shared, framework-owned components.

## The authoring surface (what a strategy author writes)

A candidate implements **one** method and declares its metadata:

```python
from quant.base import BaseStrategy, StrategySpec, PortfolioIntent, RiskControls, Scores, REGISTRY

@REGISTRY.candidate
class B1CrossSectionalMomentum(BaseStrategy):
    spec = StrategySpec(id="b1_xs_momentum", family="cross_sectional_momentum",
                        hypothesis="risk-managed XS momentum survives the null", ...)
    intent = PortfolioIntent(
        rebalance_days=30,
        risk=RiskControls(beta_neutral=True, inverse_vol_weight=True, vol_target_annual=0.15),
    )
    def score(self, features) -> Scores:
        ...  # IR-momentum (return/vol) with a 7d reversal skip -> a date x symbol panel
```

Everything else — ranking→weights, neutrality, vol-targeting, costs, walk-forward,
the rank-shuffle null, the 7-criterion gate — is shared and lives in `quant/base/`.

## Layout

```
quant/
  base/
    signal.py      Scores (date x symbol panel), Side          # what a strategy emits
    strategy.py    BaseStrategy ABC, StrategySpec, PortfolioIntent
    portfolio.py   PortfolioConstructor + DollarNeutralConstructor (T2-class baseline)
    execution.py   ExecutionModel + TakerExecution (matches current ledger)
    risk.py        RiskControls (dollar/beta-neutral, vol-target, caps, DD breaker)
    lifecycle.py   Lifecycle state machine + legal-transition guard
    registry.py    StrategyRegistry (single source of truth for stage + validations)
    metadata.py    PreRegistration, ValidationResult (the audit trail)
  candidates/      active candidates (B1 lands here next) — none yet
  retired/         falsified families, reference-only, never live
  tests/           smoke tests (5/5 pass)
  README.md
```

## How it maps onto the real harness (not invented)

- A strategy's `Scores.panel` is the same `date x symbol` DataFrame
  `tools/nautilus/xsect_signals.py` already produces.
- `PortfolioConstructor.build_schedule()` emits exactly the `schedule` shape
  `tools/nautilus/basket_ledger.simulate_basket()` consumes:
  `list[(rebalance_ts, {symbol: signed_dollar_notional})]`.
- `ExecutionModel.ledger_kwargs()` returns the `fee_rate / half_spread_bps /
  impact_coef_bps` kwargs `simulate_basket` accepts.
- `ValidationResult.criteria` stores `tools/graduation/gate.py:GateResult.criteria`
  verbatim.

The defaults (`DollarNeutralConstructor`, `TakerExecution`) reproduce the
existing T2-class construction and are runnable today. B1's additions
(`RiskManagedConstructor`: inverse-vol + portfolio vol-target + beta-neutral;
`MakerFillModel`: rebate + fill-probability + adverse-selection) are the **next
increment** and subclass these contracts — so the null control automatically
applies the identical construction to shuffled signals.

## What this increment is NOT

- It does **not** move, delete, or import any live module. Legacy `strategies/`
  (dead, nothing imports it) and the live runner are untouched.
- It does **not** implement B1's math yet — only the seams B1 plugs into.
- The eventual cleanup phase deletes the dead legacy `strategies/` tree; at that
  point `quant/` is the single canonical strategy home (rename optional).

## Next increments (in order)

1. **B1 construction code** — `RiskManagedConstructor` + `MakerFillModel` in
   `quant/base/`, then `quant/candidates/b1_xs_momentum.py`. (Needs operator
   sign-off + a committed pre-registration before any data is opened.)
2. **Harness adapter** — a thin runner that feeds a candidate through
   `xsect_walkforward` + `null_engines` + `gate` and writes a `ValidationResult`.
3. **Paper confirmation runner** — multiple candidates in parallel, each judged
   against its own pre-registration; auto-demotion; weekly scorecard.
