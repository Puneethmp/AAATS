"""Harness adapter — feed a BaseStrategy candidate through the EXISTING walk-forward
harness and emit a quant.base.ValidationResult.

This is the one piece that joins the two halves of the factory:

    candidate (quant.base)                    crown-jewel harness (tools/)
    ----------------------                    ----------------------------
    candidate.score(features) -> Scores       basket_ledger.simulate_basket
    RiskManagedConstructor.build_schedule     null_engines.null_distribution
    MakerFillModel.simulate_fills/kwargs      xsect_walkforward.{make_folds,evaluate}
                                              graduation.gate.evaluate_gate

The adapter REINVENTS NOTHING: every metric is computed by the audited harness
functions; this module only constructs the schedule with the framework's own
constructor + execution model, runs the real + null sims, maps the harness output
onto the seven graduation criteria, and records the verdict.

Purity / hard-gate discipline
-----------------------------
``run_walkforward`` is a pure function of the data passed in. It NEVER fetches real
data — ``daily_close``, ``funding`` and ``membership`` are inputs (the caller loads
them via tools.nautilus.u30_data only AFTER the pre-registration is frozen and
committed). This session exercises the adapter on SYNTHETIC data only
(see quant/tests/test_adapter_smoke.py).

Metric mapping (documented, not guessed)
----------------------------------------
The harness's ``xsect_walkforward.evaluate`` returns the program's frozen 5-part
walk-forward criterion (incl. the Bonferroni null control). The graduation gate
(``tools/graduation/gate.py``) scores SEVEN criteria from a flat metrics dict. We
map the walk-forward output onto the gate's metrics like so:

    G1 net_pnl_usd       <- sum of per-fold OOS net PnL (net of fees/funding/slip)
    G2 sharpe            <- pooled-OOS daily Sharpe         (evaluate criterion 3)
    G3 max_drawdown_pct  <- worst per-fold max drawdown     (evaluate criterion 4)
    G4 n_trades          <- OOS round-trip count            (evaluate n_oos_trades)
    G5 profit_factor     <- gross profit / gross loss over OOS round-trips
    G6 in_sample_sharpe  <- FULL-sample daily Sharpe (train+OOS) — the degradation
       oos_sharpe        <- pooled-OOS daily Sharpe; G6 asks OOS >= 0.5 * full-sample
    G7 pnl_at_maker_0_5  <- OOS net PnL when the maker fill prob is stressed to 0.5

The full 5-part walk-forward verdict (including the decisive null control, which the
7-criterion gate does NOT itself test) is preserved verbatim under
``ValidationResult.metrics['walkforward_verdict']`` so nothing is lost from the
audit trail.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # mirror tools/nautilus/run_*.py so `tools.*` resolves
    sys.path.insert(0, str(_ROOT))

from quant.base import (  # noqa: E402
    Lifecycle,
    MakerFillModel,
    MarketContext,
    REGISTRY,
    RiskManagedConstructor,
    Scores,
    ValidationResult,
)
from tools.graduation.gate import GateThresholds, evaluate_gate  # noqa: E402
from tools.nautilus.basket_ledger import (  # noqa: E402
    precompute_funding_matrix,
    simulate_basket,
)
from tools.nautilus.null_engines import null_distribution  # noqa: E402
from tools.nautilus.xsect_walkforward import (  # noqa: E402
    ANN_DAILY,
    _trades_in,
    evaluate,
    make_folds,
    sharpe,
)

DEFAULT_BOOK = 100.0  # matches the program's BOOK convention (run_t2 / basket_ledger)
DEFAULT_SEED = 7
DEFAULT_N_NULL = 1000


# --------------------------------------------------------------------------- #
# schedule construction (identical machinery for real / null / G7-stress runs)
# --------------------------------------------------------------------------- #
def _filled_schedule(constructor, scores, context, membership, exec_model, seed):
    """Build the rebalance schedule, then apply the execution fill transform.

    A fresh RNG is seeded per call so the maker-drop mask is IDENTICAL for the real
    run and every null draw given the same schedule shape (the anti-overfit
    invariant documented in quant.base.execution)."""
    schedule = constructor.build_schedule(scores, context, membership)
    return exec_model.simulate_fills(schedule, np.random.default_rng(seed))


def _oos_net_usd(trades, folds) -> float:
    """Total net PnL of round-trips closing inside any OOS fold window."""
    oos = [t for (lo, hi) in folds for t in _trades_in(trades, lo, hi)]
    return float(sum(t["pnl_net"] for t in oos))


def _oos_profit_factor(trades, folds) -> float:
    """Gross profit / gross loss over OOS round-trips (G5)."""
    oos = [t for (lo, hi) in folds for t in _trades_in(trades, lo, hi)]
    gross_profit = float(sum(t["pnl_net"] for t in oos if t["pnl_net"] > 0))
    gross_loss = float(-sum(t["pnl_net"] for t in oos if t["pnl_net"] < 0))
    if gross_loss > 0:
        return gross_profit / gross_loss
    return 1e9 if gross_profit > 0 else 0.0  # finite & JSON-serializable sentinel


def _exec_descriptor(exec_model) -> Any:
    return asdict(exec_model) if is_dataclass(exec_model) else repr(exec_model)


# --------------------------------------------------------------------------- #
# the adapter
# --------------------------------------------------------------------------- #
def run_walkforward(
    candidate,
    *,
    daily_close,
    funding,
    membership: dict | None = None,
    context: "MarketContext | None" = None,
    execution=None,
    book: float = DEFAULT_BOOK,
    seed: int = DEFAULT_SEED,
    n_null: int = DEFAULT_N_NULL,
    folds=None,
    thresholds: "GateThresholds | None" = None,
    registry=REGISTRY,
    results_dir: str = "research/results",
    falsified_path: str = "research/falsified.md",
    now: "datetime | None" = None,
    write_result: bool = True,
    update_registry: bool = True,
) -> ValidationResult:
    """Run one walk-forward gate for ``candidate`` and emit a ValidationResult.

    Parameters
    ----------
    candidate : quant.base.BaseStrategy
        Provides ``.score(features) -> Scores``, ``.intent`` and ``.spec.id``.
    daily_close : pandas.DataFrame
        days(midnight UTC) x symbols perp-close panel (from
        tools.nautilus.u30_data.load_daily_close_panel — passed in, not fetched).
    funding : dict[str, pandas.Series]
        symbol -> 8h funding-rate series (u30_data.load_funding).
    membership : dict | None
        date -> [eligible symbols] (u30_data.membership_by_date). None = all symbols
        eligible every rebalance.
    context : MarketContext | None
        Per-date vol/beta source. Defaults to MarketContext.from_close(daily_close).
    execution : ExecutionModel | None
        Defaults to MakerFillModel() (B1's frozen maker assumptions). Must expose
        ``.stressed(0.5)`` for the G7 robustness leg if maker-based.
    book : float
        Capital base; the constructor scales notionals to it AND the ledger
        normalizes returns by it, so the SAME value flows to both.
    seed, n_null : int
        Null-distribution controls (frozen seed=7, 1000 draws).
    folds : optional
        Override the OOS fold geometry; defaults to make_folds over the data span.

    Returns
    -------
    ValidationResult with the gate's pass/fail, per-criterion breakdown (G1..G7),
    and a metrics dict carrying the full walk-forward verdict (incl. null control).
    Also writes the result immutably to ``results_dir`` and, on a terminal verdict,
    updates ``registry`` (promote on PASS / demote + falsified-log on FAIL).
    """
    cid = candidate.spec.id
    now = now or datetime.now(timezone.utc)
    execution = execution if execution is not None else MakerFillModel()
    context = context if context is not None else MarketContext.from_close(daily_close)
    thresholds = thresholds if thresholds is not None else GateThresholds()
    if folds is None:
        folds = make_folds(daily_close.index[0], daily_close.index[-1])

    constructor = RiskManagedConstructor(candidate.intent, book=book)

    # --- real run -----------------------------------------------------------
    scores = candidate.score({"daily_close": daily_close})
    real_schedule = _filled_schedule(
        constructor, scores, context, membership, execution, seed
    )
    fund_mat = precompute_funding_matrix(daily_close, funding)
    real_result = simulate_basket(
        daily_close,
        funding,
        real_schedule,
        book,
        funding_rate_mat=fund_mat,
        **execution.ledger_kwargs(),
    )

    # --- null distribution (identical constructor + execution on shuffled scores)
    def _null_builder(scores_df):
        return _filled_schedule(
            constructor,
            Scores(panel=scores_df, name="null"),
            context,
            membership,
            execution,
            seed,
        )

    def _null_simulate(schedule):
        return simulate_basket(
            daily_close,
            funding,
            schedule,
            book,
            funding_rate_mat=fund_mat,
            compute_trades=False,
            **execution.ledger_kwargs(),
        )

    null_sharpes = null_distribution(
        _null_builder,
        _null_simulate,
        daily_close.index,
        list(daily_close.columns),
        folds,
        book,
        n=n_null,
        seed=seed,
    )

    # --- frozen 5-part walk-forward verdict (incl. Bonferroni null control) --
    wf = evaluate(real_result, folds, null_sharpes)

    # --- G7 maker-fill robustness leg (fill prob stressed to 0.5) -----------
    stressed = execution.stressed(0.5) if hasattr(execution, "stressed") else execution
    stressed_schedule = _filled_schedule(
        constructor, scores, context, membership, stressed, seed
    )
    stressed_result = simulate_basket(
        daily_close,
        funding,
        stressed_schedule,
        book,
        funding_rate_mat=fund_mat,
        **stressed.ledger_kwargs(),
    )
    pnl_at_maker_0_5 = _oos_net_usd(stressed_result.trades, folds)

    # --- map walk-forward output onto the seven graduation criteria ---------
    crit = wf["criteria"]
    pooled_oos_sharpe = float(crit["3_pooled_oos_daily_sharpe"]["value"])
    full_sample_sharpe = sharpe(real_result.daily_returns.to_numpy(), ANN_DAILY)
    metrics: dict[str, Any] = {
        "net_pnl_usd": _oos_net_usd(real_result.trades, folds),
        "sharpe": pooled_oos_sharpe,
        "max_drawdown_pct": float(crit["4_worst_fold_maxdd"]["value"]),
        "n_trades": int(wf["n_oos_trades"]),
        "profit_factor": _oos_profit_factor(real_result.trades, folds),
        "in_sample_sharpe": full_sample_sharpe,
        "oos_sharpe": pooled_oos_sharpe,
        "pnl_at_maker_0_5": pnl_at_maker_0_5,
    }
    gate = evaluate_gate(metrics, thresholds)

    # the full audit trail (the gate alone does not test the decisive null) ---
    metrics["walkforward_verdict"] = wf
    metrics["null_control_passed"] = bool(crit["5_null_control"]["passed"])
    metrics["book_usd"] = book
    metrics["seed"] = seed
    metrics["n_null_draws"] = int(n_null)
    metrics["n_folds"] = len(folds)
    metrics["execution"] = _exec_descriptor(execution)

    result = ValidationResult(
        strategy_id=cid,
        stage="walkforward",
        passed=gate.passed,
        failures=list(gate.failures),
        criteria=gate.criteria,
        metrics=metrics,
        evaluated_at=now.isoformat(),
        seed=seed,
    )

    if write_result:
        _write_result(result, results_dir, now)
    if update_registry:
        _update_registry(registry, result, falsified_path, now)
    return result


# --------------------------------------------------------------------------- #
# side effects: immutable result log + registry promotion/demotion
# --------------------------------------------------------------------------- #
def _write_result(result: ValidationResult, results_dir: str, now: datetime) -> str:
    out = Path(results_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    path = out / f"{result.strategy_id}_walkforward_{stamp}.json"
    path.write_text(
        json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    return str(path)


def _update_registry(
    registry, result: ValidationResult, falsified_path: str, now: datetime
) -> None:
    sid = result.strategy_id
    try:
        registry.record_validation(result)
    except KeyError:
        # candidate not registered in this registry — nothing to update
        return
    if result.passed:
        registry.promote(sid, Lifecycle.WALKFORWARD)
    else:
        registry.demote(sid)
        _append_falsified(falsified_path, result, now)


def _append_falsified(
    falsified_path: str, result: ValidationResult, now: datetime
) -> None:
    """Append a one-line FAIL record to research/falsified.md (process mandate)."""
    p = Path(falsified_path)
    why = "; ".join(result.failures) if result.failures else "gate FAIL"
    line = f"| {now.date()} | {result.strategy_id} (walk-forward) | FAIL | {why} |\n"
    if p.exists():
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# Falsified Hypotheses — index\n\n"
            "| Date | Hypothesis / strategy | Verdict | Why it failed |\n"
            "|---|---|---|---|\n" + line,
            encoding="utf-8",
        )
