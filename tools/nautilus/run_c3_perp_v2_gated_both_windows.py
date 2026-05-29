"""B.1.7 Track 10 driver — C3-perp + regime gate v2 (divergence AND correlation).

Runs the C3-perp funded harness on the current (Nov25→May26) and earlier
(Nov24→May25) windows at gate_version=2 (Track 10: divergence>0.08 OR
correlation<0.5 blocks new entries). For context it re-runs each window UNGATED
(v0) and divergence-only (v1, Track 9) so the six-row table is built from live
actuals, not hard-coded baselines.

Hypothesis (Track 10): ANDing a 30d rolling BTC-alt correlation signal onto the
divergence gate rescues the earlier window without hurting the current window,
because correlation directly measures C3's mean-reversion thesis assumption
(alts and BTC co-moving) and is structurally independent of the divergence level.

Writes the two v2 graduation reports:
    data/graduation/C3_perp_gated_v2_current_<today>.json
    data/graduation/C3_perp_gated_v2_earlier_<today>.json
The v0/v1 re-runs are diagnostic only (emit=False — not written).

    python3 tools/nautilus/run_c3_perp_v2_gated_both_windows.py
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.nautilus.run_c3_perp_funded_oos as cur
import tools.nautilus.run_c3_perp_funded_earlier_oos as earl


def _row(label, gate_v, metrics, result):
    return {
        "label": label,
        "gate_v": gate_v,
        "gate_pct": metrics["gate_active_pct"],
        "n_trades": metrics["n_trades"],
        "pnl": metrics["net_pnl_usd"],
        "sharpe": metrics["oos_sharpe"],
        "pf": metrics["profit_factor"],
        "verdict": "PASS" if result.passed else "FAIL",
    }


def _corr_summary(taker):
    c = taker.get("correlations", [])
    if not c:
        return "n/a"
    arr = np.array(c)
    below = int((arr < 0.50).sum())
    return (
        f"n={len(arr)} min={arr.min():+.3f} mean={arr.mean():+.3f} "
        f"max={arr.max():+.3f}  bars<0.50={below} ({100 * below / len(arr):.1f}%)"
    )


def _run_window(mod, name):
    """Return (v0_row_inputs, v1_row_inputs, v2_row_inputs, v2_metrics, v2_taker, v2_path)."""
    v0_m, v0_r, *_ = mod.evaluate(gate_version=0, emit=False, verbose=False)
    v1_m, v1_r, *_ = mod.evaluate(gate_version=1, emit=False, verbose=False)
    v2_m, v2_r, v2_t, _mt, v2_path = mod.evaluate(
        gate_version=2,
        strategy_name=f"C3_perp_gated_v2_{name}",
        emit=True,
        verbose=False,
    )
    return {
        "v0": _row(f"{name}-ungated", 0, v0_m, v0_r),
        "v1": _row(f"{name}-v1", 1, v1_m, v1_r),
        "v2": _row(f"{name}-v2", 2, v2_m, v2_r),
        "v2_metrics": v2_m,
        "v2_result": v2_r,
        "v2_taker": v2_t,
        "v2_path": v2_path,
    }


def main():
    print(">>> CURRENT window (Nov25->May26): v0 + v1 + v2")
    cur_res = _run_window(cur, "current")
    print(">>> EARLIER window (Nov24->May25): v0 + v1 + v2")
    earl_res = _run_window(earl, "earlier")

    rows = [
        cur_res["v0"],
        cur_res["v1"],
        cur_res["v2"],
        earl_res["v0"],
        earl_res["v1"],
        earl_res["v2"],
    ]

    print("\n============== C3-PERP REGIME-GATE v2 DUAL-WINDOW ==============")
    print(
        f"{'window':<17}|{'gate_v':>7}|{'gate%':>7}|{'n_trades':>9}|{'pnl':>8}|"
        f"{'sharpe':>8}|{'PF':>6}| verdict"
    )
    print("-" * 80)
    for r in rows:
        print(
            f"{r['label']:<17}|{r['gate_v']:>7}|{r['gate_pct']:>7.1f}|"
            f"{r['n_trades']:>9}|{r['pnl']:>+8.2f}|{r['sharpe']:>8.2f}|"
            f"{r['pf']:>6.2f}| {r['verdict']}"
        )

    print("\n--- TWO-SIGNAL GATE DIAGNOSTIC (v2) ---")
    for name, res in (("CURRENT", cur_res), ("EARLIER", earl_res)):
        m, t = res["v2_metrics"], res["v2_taker"]
        blocked = m["gate_blocked_bars"]
        print(
            f"{name} v2: active {m['gate_active_pct']:.1f}% "
            f"({blocked}/{m['gate_eval_bars']} bars) | block attribution: "
            f"div_only={m['gate_block_div_only']} corr_only={m['gate_block_corr_only']} "
            f"both={m['gate_block_both']}"
        )
        print(f"  mean 30d correlation: {m['mean_correlation_30d']}")
        print(f"  correlation series: {_corr_summary(t)}")
        print(f"  blocked-by-month: {m['_gate_blocked_months']}")

    print("\nreports:")
    print(f"  {cur_res['v2_path']}")
    print(f"  {earl_res['v2_path']}")

    print("\n--- VERDICTS (v2) ---")
    cv, ev = cur_res["v2_result"], earl_res["v2_result"]
    cm, em = cur_res["v2_metrics"], earl_res["v2_metrics"]
    print(
        f"C3-perp gated v2 CURRENT: {'PASS' if cv.passed else 'FAIL'}"
        f"  (PF {cm['profit_factor']}, net {cm['net_pnl_usd']:+.2f})"
    )
    if not cv.passed:
        print(f"    failures: {cv.failures}")
    print(
        f"C3-perp gated v2 EARLIER: {'PASS' if ev.passed else 'FAIL'}"
        f"  (PF {em['profit_factor']}, net {em['net_pnl_usd']:+.2f})"
    )
    if not ev.passed:
        print(f"    failures: {ev.failures}")
    both = cv.passed and ev.passed
    robust = "YES" if both else ("PARTIAL" if cv.passed else "NO")
    print(f"Robust live-flip candidate: {robust}")


if __name__ == "__main__":
    main()
