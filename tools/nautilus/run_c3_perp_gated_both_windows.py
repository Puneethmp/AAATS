"""B.1.7 Track 9 driver — C3-perp + allocator regime gate, BOTH windows.

Runs the C3-perp funded harness on the current (Nov25→May26) and earlier
(Nov24→May25) windows, each WITH the allocator-level regime gate enabled
(tools/nautilus/regime_gate.py: 30d BTC-vs-alt return divergence > 0.08 blocks
new entries). For context it also re-runs each window UNGATED so the four-row
table is built from live actuals, not hard-coded baselines.

The hypothesis (Track 9): a principled regime gate that skips the
BTC-up/alts-down decoupling regime restores C3-perp to a PASS on BOTH windows —
which Track 8 showed the ungated strategy cannot do (PF 1.45 current, PF 0.71
earlier).

Writes the two GATED graduation reports:
    data/graduation/C3_perp_gated_current_<today>.json
    data/graduation/C3_perp_gated_earlier_<today>.json

The ungated re-runs are diagnostic only (emit=False — not written).

    python3 tools/nautilus/run_c3_perp_gated_both_windows.py
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


def _row(label, metrics, result):
    return {
        "label": label,
        "gate_pct": metrics["gate_active_pct"],
        "n_trades": metrics["n_trades"],
        "pnl": metrics["net_pnl_usd"],
        "sharpe": metrics["oos_sharpe"],
        "pf": metrics["profit_factor"],
        "verdict": "PASS" if result.passed else "FAIL",
    }


def _divergence_summary(taker):
    d = taker.get("divergences", [])
    if not d:
        return "n/a"
    arr = np.array(d)
    above = int((arr > 0.08).sum())
    return (
        f"n={len(arr)} min={arr.min():+.3f} mean={arr.mean():+.3f} "
        f"max={arr.max():+.3f}  bars>0.08={above} ({100 * above / len(arr):.1f}%)"
    )


def main():
    print(">>> CURRENT window (Nov25->May26): ungated baseline + gated")
    cu_m, cu_r, _cu_t, _cu_mt, _ = cur.evaluate(
        use_regime_gate=False, emit=False, verbose=False
    )
    cg_m, cg_r, cg_t, _cg_mt, cg_path = cur.evaluate(
        use_regime_gate=True,
        strategy_name="C3_perp_gated_current",
        emit=True,
        verbose=False,
    )

    print(">>> EARLIER window (Nov24->May25): ungated baseline + gated")
    eu_m, eu_r, _eu_t, _eu_mt, _ = earl.evaluate(
        use_regime_gate=False, emit=False, verbose=False
    )
    eg_m, eg_r, eg_t, _eg_mt, eg_path = earl.evaluate(
        use_regime_gate=True,
        strategy_name="C3_perp_gated_earlier",
        emit=True,
        verbose=False,
    )

    rows = [
        _row("current-ungated", cu_m, cu_r),
        _row("current-gated  ", cg_m, cg_r),
        _row("earlier-ungated", eu_m, eu_r),
        _row("earlier-gated  ", eg_m, eg_r),
    ]

    print("\n================= C3-PERP REGIME-GATE DUAL-WINDOW =================")
    print(
        f"{'window':<16}| {'gate%':>6} | {'n_trades':>8} | {'pnl':>8} | "
        f"{'sharpe':>7} | {'PF':>6} | verdict"
    )
    print("-" * 75)
    for r in rows:
        print(
            f"{r['label']:<16}| {r['gate_pct']:>6.1f} | {r['n_trades']:>8} | "
            f"{r['pnl']:>+8.2f} | {r['sharpe']:>7.2f} | {r['pf']:>6.2f} | {r['verdict']}"
        )

    print("\n--- GATE DIAGNOSTIC ---")
    print(
        f"CURRENT gated: active {cg_m['gate_active_pct']:.1f}% "
        f"({cg_m['gate_blocked_bars']}/{cg_m['gate_eval_bars']} computable bars)"
    )
    print(f"  divergence: {_divergence_summary(cg_t)}")
    print(f"  blocked-by-month: {cg_m['_gate_blocked_months']}")
    print(
        f"EARLIER gated: active {eg_m['gate_active_pct']:.1f}% "
        f"({eg_m['gate_blocked_bars']}/{eg_m['gate_eval_bars']} computable bars)"
    )
    print(f"  divergence: {_divergence_summary(eg_t)}")
    print(f"  blocked-by-month: {eg_m['_gate_blocked_months']}")

    print("\nreports:")
    print(f"  {cg_path}")
    print(f"  {eg_path}")

    print("\n--- VERDICTS ---")
    print(
        f"C3-perp gated CURRENT: {'PASS' if cg_r.passed else 'FAIL'}"
        f"  (PF {cg_m['profit_factor']}, net {cg_m['net_pnl_usd']:+.2f})"
    )
    if not cg_r.passed:
        print(f"    failures: {cg_r.failures}")
    print(
        f"C3-perp gated EARLIER: {'PASS' if eg_r.passed else 'FAIL'}"
        f"  (PF {eg_m['profit_factor']}, net {eg_m['net_pnl_usd']:+.2f})"
    )
    if not eg_r.passed:
        print(f"    failures: {eg_r.failures}")
    both = cg_r.passed and eg_r.passed
    robust = "YES" if both else ("PARTIAL" if cg_r.passed else "NO")
    print(f"Robust live-flip candidate: {robust}")


if __name__ == "__main__":
    main()
