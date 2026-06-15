"""Adapter smoke test — runs the WHOLE harness chain on SYNTHETIC data.

Opens NO real data (the hard pre-registration gate forbids it this session). It
builds a synthetic multi-symbol price/funding panel long enough to yield ≥1 OOS
fold, runs quant.research.adapter.run_walkforward end-to-end through the real
harness (constructor -> maker fills -> simulate_basket -> null distribution ->
evaluate -> evaluate_gate), and asserts a ValidationResult with all seven
graduation criteria is produced, logged, and reflected in the registry.

Reuses the synthetic-generator style of test_b1_construction.py (beta/sigma per
symbol, market factor + idiosyncratic noise), extended to a ~15-month daily span
so make_folds produces real OOS windows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from quant.base import Lifecycle, StrategyRegistry
from quant.candidates.b1_xs_momentum import B1CrossSectionalMomentum
from quant.research.adapter import run_walkforward

_GATE_KEYS = {"G1", "G2", "G3", "G4", "G5", "G6", "G7"}


def _synth_market(n_days: int = 460, seed: int = 7):
    """Synthetic daily_close + funding + membership for ~15 months (folds exist)."""
    rng = np.random.default_rng(seed)
    syms = ["A", "B", "C", "D", "E", "F", "G", "H"]
    betas = dict(zip(syms, [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]))
    sigmas = dict(zip(syms, [0.005, 0.02, 0.01, 0.03, 0.008, 0.025, 0.015, 0.035]))
    drifts = dict(
        zip(syms, [0.0010, -0.0005, 0.0008, -0.0003, 0.0006, -0.0007, 0.0004, -0.0002])
    )
    idx = pd.date_range("2025-01-01", periods=n_days, freq="D", tz="UTC")
    mkt = rng.normal(0.0, 0.015, n_days)
    close = {}
    for s in syms:
        ret = drifts[s] + betas[s] * mkt + rng.normal(0.0, sigmas[s], n_days)
        close[s] = 100.0 * np.exp(np.cumsum(ret))
    daily_close = pd.DataFrame(close, index=idx)

    # 8h funding settlements over the same span, small mean-zero rates
    f_idx = pd.date_range(idx[0], idx[-1], freq="8h", tz="UTC")
    funding = {
        s: pd.Series(rng.normal(0.0, 1e-4, len(f_idx)), index=f_idx) for s in syms
    }
    return daily_close, funding


def test_adapter_end_to_end_synthetic(tmp_path):
    daily_close, funding = _synth_market()

    # fresh registry; pre-registration assumed done -> candidate sits at BACKTEST,
    # the only legal source state for a -> WALKFORWARD promotion.
    reg = StrategyRegistry()
    candidate = B1CrossSectionalMomentum()
    reg.register(candidate)
    reg.promote(candidate.spec.id, Lifecycle.BACKTEST)

    fixed_now = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    result = run_walkforward(
        candidate,
        daily_close=daily_close,
        funding=funding,
        membership=None,
        book=100.0,
        seed=7,
        n_null=40,  # small for test speed; real run uses 1000
        registry=reg,
        results_dir=str(tmp_path / "results"),
        falsified_path=str(tmp_path / "falsified.md"),
        now=fixed_now,
    )

    # --- a ValidationResult with all seven criteria present -----------------
    assert result.strategy_id == "b1_xs_momentum"
    assert result.stage == "walkforward"
    assert set(result.criteria) == _GATE_KEYS, result.criteria.keys()
    assert isinstance(result.passed, bool)
    for g in _GATE_KEYS:
        assert "passed" in result.criteria[g]

    # --- gate metrics + full walk-forward audit trail preserved ------------
    for key in (
        "net_pnl_usd",
        "sharpe",
        "max_drawdown_pct",
        "n_trades",
        "profit_factor",
        "in_sample_sharpe",
        "oos_sharpe",
        "pnl_at_maker_0_5",
    ):
        assert key in result.metrics
    wf = result.metrics["walkforward_verdict"]
    assert set(wf["criteria"]) >= {
        "3_pooled_oos_daily_sharpe",
        "4_worst_fold_maxdd",
        "5_null_control",
    }
    assert result.metrics["n_folds"] >= 1
    assert "null_control_passed" in result.metrics

    # --- immutable result file written -------------------------------------
    files = list((tmp_path / "results").glob("b1_xs_momentum_walkforward_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["stage"] == "walkforward"
    assert set(payload["criteria"]) == _GATE_KEYS

    # --- registry reflects the terminal verdict ----------------------------
    state = reg.state_of(candidate.spec.id)
    if result.passed:
        assert state == Lifecycle.WALKFORWARD
    else:
        assert state == Lifecycle.RETIRED
        assert (tmp_path / "falsified.md").exists()
    assert reg._entries[candidate.spec.id].validations[-1] is result


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        test_adapter_end_to_end_synthetic(Path(d))
    print("PASS test_adapter_end_to_end_synthetic")
