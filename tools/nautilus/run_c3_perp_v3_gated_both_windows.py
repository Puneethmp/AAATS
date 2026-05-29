"""B.1.7 Track 11 driver — C3-perp + regime gate v3 (divergence AND drift).

Runs the C3-perp funded harness at gate_version=3 (Track 11: divergence>0.08 OR
|60d log-RS drift|>=0.08 blocks new entries) on the current (Nov25->May26) and
earlier (Nov24->May25) windows, and answers the ONE Track 11 question: does the
drift gate flip the earlier window from FAIL to PASS?

Track 10 closed the co-movement avenue — correlation was inert (corr_only=0 in
BOTH windows; it never blocked a single bar). The drift/trend signal is the LAST
cheap entry-gate experiment named by Track 10: a longer-horizon relative-strength
trend on the pair's own legs, targeting the diagnosed low-frequency relative
DRIFT (BTC up, alts bleeding) rather than the high-frequency decorrelation that
correlation measured and that never happened.

To honour the Track 11 hard constraint "do NOT re-run current-window v1/v2 —
locked at 7/7", this driver RUNS only the genuinely-new evaluations:
    current: v0 (ungated context) + v3
    earlier: v0 (ungated context) + v1 (in-session FAIL baseline) + v3
and CITES the locked v1/v2 rows from the Track 9/10 graduation reports already on
disk (read-only) to assemble the full comparison table. Nothing current-v1/v2 is
recomputed.

Writes the two v3 graduation reports:
    data/graduation/C3_perp_gated_v3_current_<today>.json
    data/graduation/C3_perp_gated_v3_earlier_<today>.json

    python3 tools/nautilus/run_c3_perp_v3_gated_both_windows.py
"""

# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.nautilus.run_c3_perp_funded_oos as cur
import tools.nautilus.run_c3_perp_funded_earlier_oos as earl

GRAD = ROOT / "data" / "graduation"


def _row(label, gate_v, metrics, verdict):
    return {
        "label": label,
        "gate_v": gate_v,
        "gate_pct": metrics["gate_active_pct"],
        "n_trades": metrics["n_trades"],
        "pnl": metrics["net_pnl_usd"],
        "sharpe": metrics["oos_sharpe"],
        "pf": metrics["profit_factor"],
        "verdict": verdict,
    }


def _cite_row(label, gate_v, report_name):
    """Build a comparison row from a locked on-disk graduation report (read-only)."""
    p = GRAD / report_name
    payload = json.loads(p.read_text(encoding="utf-8"))
    return _row(label, gate_v, payload["metrics"], payload["verdict"]), str(p)


def _drift_summary(taker):
    d = taker.get("drifts", [])
    if not d:
        return "n/a"
    arr = np.array(d)
    over = int((np.abs(arr) >= 0.08).sum())
    return (
        f"n={len(arr)} min={arr.min():+.4f} mean={arr.mean():+.4f} "
        f"max={arr.max():+.4f}  |drift|>=0.08={over} ({100 * over / len(arr):.1f}%)"
    )


def _verdict(result):
    return "PASS" if result.passed else "FAIL"


def _run_window(mod, name, run_v1: bool):
    v0_m, v0_r, *_ = mod.evaluate(gate_version=0, emit=False, verbose=False)
    out = {"v0": _row(f"{name}-ungated", 0, v0_m, _verdict(v0_r))}
    if run_v1:
        v1_m, v1_r, *_ = mod.evaluate(gate_version=1, emit=False, verbose=False)
        out["v1"] = _row(f"{name}-v1", 1, v1_m, _verdict(v1_r))
    v3_m, v3_r, v3_t, _mt, v3_path = mod.evaluate(
        gate_version=3,
        strategy_name=f"C3_perp_gated_v3_{name}",
        emit=True,
        verbose=False,
    )
    out.update(
        {
            "v3": _row(f"{name}-v3", 3, v3_m, _verdict(v3_r)),
            "v3_metrics": v3_m,
            "v3_result": v3_r,
            "v3_taker": v3_t,
            "v3_path": v3_path,
        }
    )
    return out


def main():
    today = date.today().isoformat()
    print(">>> CURRENT window (Nov25->May26): v0 + v3  (v1/v2 cited, locked 7/7)")
    cur_res = _run_window(cur, "current", run_v1=False)
    print(">>> EARLIER window (Nov24->May25): v0 + v1 + v3")
    earl_res = _run_window(earl, "earlier", run_v1=True)

    # Cited (read-only) rows — Track 9 (v1) + Track 10 (v2) locked reports.
    cur_v1, cur_v1_src = _cite_row(
        "current-v1*", 1, f"C3_perp_gated_current_{today}.json"
    )
    cur_v2, cur_v2_src = _cite_row(
        "current-v2*", 2, f"C3_perp_gated_v2_current_{today}.json"
    )
    earl_v2, earl_v2_src = _cite_row(
        "earlier-v2*", 2, f"C3_perp_gated_v2_earlier_{today}.json"
    )

    rows = [
        cur_res["v0"],
        cur_v1,
        cur_v2,
        cur_res["v3"],
        earl_res["v0"],
        earl_res["v1"],
        earl_v2,
        earl_res["v3"],
    ]

    print(
        "\n========== C3-PERP REGIME-GATE v3 DUAL-WINDOW (* = cited/locked) =========="
    )
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

    print("\n--- DRIFT-GATE ATTRIBUTION DIAGNOSTIC (v3) — CHECK THIS FIRST ---")
    for name, res in (("CURRENT", cur_res), ("EARLIER", earl_res)):
        m, t = res["v3_metrics"], res["v3_taker"]
        blocked = m["gate_blocked_bars"]
        print(
            f"{name} v3: active {m['gate_active_pct']:.1f}% "
            f"({blocked}/{m['gate_eval_bars']} bars) | block attribution: "
            f"div_only={m['gate_block_div_only']} "
            f"drift_only={m['gate_block_drift_only']} "
            f"both={m['gate_block_both']}"
        )
        print(
            f"  drift computable on {m['drift_eval_bars']} bars; "
            f"mean 60d drift: {m['mean_drift_60d']}"
        )
        print(f"  drift series: {_drift_summary(t)}")
        print(f"  blocked-by-month: {m['_gate_blocked_months']}")

    print("\nreports written:")
    print(f"  {cur_res['v3_path']}")
    print(f"  {earl_res['v3_path']}")
    print("cited (read-only):")
    print(f"  {cur_v1_src}\n  {cur_v2_src}\n  {earl_v2_src}")

    print("\n--- VERDICTS (v3) ---")
    cv, ev = cur_res["v3_result"], earl_res["v3_result"]
    cm, em = cur_res["v3_metrics"], earl_res["v3_metrics"]
    print(
        f"C3-perp gated v3 CURRENT: {_verdict(cv)}"
        f"  (PF {cm['profit_factor']}, net {cm['net_pnl_usd']:+.2f})"
    )
    if not cv.passed:
        print(f"    failures: {cv.failures}")
    print(
        f"C3-perp gated v3 EARLIER: {_verdict(ev)}"
        f"  (PF {em['profit_factor']}, net {em['net_pnl_usd']:+.2f})"
    )
    if not ev.passed:
        print(f"    failures: {ev.failures}")

    earlier_flipped = ev.passed  # the ONE Track 11 question
    print(
        f"\nEARLIER-WINDOW v3 FLIP (FAIL->PASS)? {'YES' if earlier_flipped else 'NO'}"
    )
    both = cv.passed and ev.passed
    robust = "YES" if both else ("PARTIAL" if cv.passed else "NO")
    print(f"Robust both-window live-flip candidate: {robust}")


if __name__ == "__main__":
    main()
