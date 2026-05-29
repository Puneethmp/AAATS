"""Static C3+TSMOM ensemble confirmation + fee-economics floor (Track F, 2026-05-30).

Operator decision: do NOT build a regime-conditional ensemble — a static blend
cannot graduate because, on the earlier-window OOS, BOTH legs lose (C3 OOS
Sharpe -1.61, TSMOM -0.92), and a portfolio mean is LINEAR in its components, so
any positive-weighted blend has negative OOS mean -> negative OOS Sharpe,
INDEPENDENT of correlation. This script confirms that falsifiably and then tests
whether fee economics moot the whole hunt. Both tasks use data already on disk
(re-runs the cached-parquet backtests; NO new fetch, NO infra).

Task 1 — STATIC ENSEMBLE (no regime detector, no timing overlay):
  Re-run the C3-perp-gated (gate_version=1, the best/divergence gate) and the
  Perp-TSMOM per-trade ledgers for both windows, blend them, and score the
  UNCHANGED G1-G7 gate on the blended book. Equal-weight = 50% capital sleeve to
  each strategy on a $100 book (per-trade return is sleeve-invariant; net $ and
  drawdown are not). Inverse-vol weights also reported. Predicted: G1 passes
  (net +ve full-window) but G2/G6 FAIL because OOS mean is negative.

Task 2 — ECONOMICS FLOOR (Option D): from the same ledgers, per-trade fee drag,
  fee fraction of the pre-fee edge, the break-even round-trip fee, and the
  $25-tranche scaling. Note: %-based fees make the net SIGN tranche-invariant
  (gross and fees scale together) — the lever is the fee TIER, not tranche size.

    .venv-nt/Scripts/python tools/nautilus/run_ensemble_and_economics.py
"""

# ruff: noqa: E402  — sys.path bootstrap (below) must precede repo-local imports
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import tools.nautilus.run_c3_perp_funded_oos as c3_cur
import tools.nautilus.run_c3_perp_funded_earlier_oos as c3_earl
import tools.nautilus.run_perp_tsmom_oos as tsmom
from tools.graduation.gate import evaluate_gate, emit_report

GATE_V = 1  # C3 best gate (divergence); v2 inert, v3 harmful (Track 10/11)
ANN = np.sqrt(
    60.0
)  # per-trade annualisation — identical to every harness in the family
C3_RT_FEE = 0.001  # C3 round-trip taker = 2 x 5bps (MARKET both legs)
START_CAPITAL = 100.0

WINDOWS = {
    "current": {"c3": c3_cur, "cutoff": pd.Timestamp("2026-03-28", tz="UTC")},
    "earlier": {"c3": c3_earl, "cutoff": pd.Timestamp("2025-03-28", tz="UTC")},
}


def _sharpe(rets):
    rets = np.asarray(rets, dtype=float)
    if len(rets) < 2 or rets.std(ddof=1) <= 1e-12:
        return 0.0
    return float(rets.mean() / rets.std(ddof=1) * ANN)


def c3_ledger(mod, maker):
    out = mod.run_backtest(maker=maker, gate_version=GATE_V)
    return [
        {"pnl_net": r["pnl_net"], "notional": r["notional"], "ts": r["ts"]}
        for r in out["trades"]
    ]


def tsmom_ledger(window, fee):
    trades, _ = tsmom._backtest(window, fee)
    return [
        {"pnl_net": r["pnl_net"], "notional": r["notional"], "ts": r["ts"]}
        for r in trades
    ]


def _leg_oos_is(rows, cut):
    """(IS mean ret, OOS mean ret, IS pnl, OOS pnl) for one leg's ledger."""
    is_r = [r["pnl_net"] / r["notional"] for r in rows if r["ts"] < cut]
    oos_r = [r["pnl_net"] / r["notional"] for r in rows if r["ts"] >= cut]
    is_p = sum(r["pnl_net"] for r in rows if r["ts"] < cut)
    oos_p = sum(r["pnl_net"] for r in rows if r["ts"] >= cut)
    return (
        float(np.mean(is_r)) if is_r else 0.0,
        float(np.mean(oos_r)) if oos_r else 0.0,
        is_p,
        oos_p,
    )


def blend_gate_metrics(c3_rows, ts_rows, cut, c3_maker_net, ts_maker_net, w=(0.5, 0.5)):
    """Equal-weight (or weighted) blended book scored in the harness's own
    per-trade sqrt(60) convention. Sleeve weight w scales $ PnL; per-trade return
    is sleeve-invariant so Sharpe = pooled native returns (the blended book takes
    every trade from both legs)."""
    pooled = sorted(
        [
            {
                "ret": r["pnl_net"] / r["notional"],
                "pnl": r["pnl_net"],
                "ts": r["ts"],
                "wi": w[0],
            }
            for r in c3_rows
        ]
        + [
            {
                "ret": r["pnl_net"] / r["notional"],
                "pnl": r["pnl_net"],
                "ts": r["ts"],
                "wi": w[1],
            }
            for r in ts_rows
        ],
        key=lambda x: x["ts"],
    )
    rets = np.array([x["ret"] for x in pooled])
    is_rets = np.array([x["ret"] for x in pooled if x["ts"] < cut])
    oos_rets = np.array([x["ret"] for x in pooled if x["ts"] >= cut])
    blpnl = np.array([x["wi"] * x["pnl"] for x in pooled])  # $ on the weighted book
    equity = START_CAPITAL + np.cumsum(blpnl)
    peak = np.maximum.accumulate(equity)
    max_dd = float(np.max((peak - equity) / peak)) if len(equity) else 0.0
    gains = blpnl[blpnl > 0].sum()
    losses = -blpnl[blpnl < 0].sum()
    metrics = {
        "net_pnl_usd": round(float(blpnl.sum()), 4),
        "sharpe": round(_sharpe(oos_rets), 4),
        "oos_sharpe": round(_sharpe(oos_rets), 4),
        "in_sample_sharpe": round(_sharpe(is_rets), 4),
        "max_drawdown_pct": round(max_dd, 4),
        "n_trades": int(len(pooled)),
        "profit_factor": round(float(gains / losses), 4)
        if losses > 0
        else float("inf"),
        "pnl_at_maker_0_5": round(w[0] * c3_maker_net + w[1] * ts_maker_net, 4),
        "_full_sharpe": round(_sharpe(rets), 4),
        "_oos_mean_ret": round(float(oos_rets.mean()) if len(oos_rets) else 0.0, 6),
        "_is_mean_ret": round(float(is_rets.mean()) if len(is_rets) else 0.0, 6),
        "_weights_c3_tsmom": list(w),
        "_construction": "50/50 capital sleeves on $100 book; pooled per-trade sqrt(60) Sharpe (sleeve-invariant); UNCHANGED G1-G7",
    }
    return metrics


def main():
    print("Re-running ledgers from cached parquet data (no fetch)...\n")
    summary = {}
    for win, cfg in WINDOWS.items():
        cut = int(cfg["cutoff"].value)
        c3_t = c3_ledger(cfg["c3"], maker=False)
        c3_m = c3_ledger(cfg["c3"], maker=True)
        ts_t = tsmom_ledger(win, tsmom.FEE_TAKER)
        ts_m = tsmom_ledger(win, tsmom.FEE_MAKER)
        c3_net = sum(r["pnl_net"] for r in c3_t)
        ts_net = sum(r["pnl_net"] for r in ts_t)
        c3_mnet = sum(r["pnl_net"] for r in c3_m)
        ts_mnet = sum(r["pnl_net"] for r in ts_m)
        c3_notional = sum(r["notional"] for r in c3_t)
        ts_notional = sum(r["notional"] for r in ts_t)

        # per-leg OOS/IS (the linear-mean evidence)
        c3_ism, c3_oosm, c3_isp, c3_oosp = _leg_oos_is(c3_t, cut)
        ts_ism, ts_oosm, ts_isp, ts_oosp = _leg_oos_is(ts_t, cut)

        # inverse-vol weights (full-window per-trade return vol)
        c3_vol = float(np.std([r["pnl_net"] / r["notional"] for r in c3_t], ddof=1))
        ts_vol = float(np.std([r["pnl_net"] / r["notional"] for r in ts_t], ddof=1))
        iv = np.array([1 / c3_vol, 1 / ts_vol])
        iv = iv / iv.sum()  # sums to 1

        ew = blend_gate_metrics(c3_t, ts_t, cut, c3_mnet, ts_mnet, w=(0.5, 0.5))
        ivm = blend_gate_metrics(c3_t, ts_t, cut, c3_mnet, ts_mnet, w=tuple(iv))
        ew_res = evaluate_gate(ew)
        iv_res = evaluate_gate(ivm)
        ew_path = emit_report(
            f"Ensemble_EW_{win}", ew, ew_res, out_dir=str(ROOT / "data" / "graduation")
        )

        # --- economics ---
        c3_fees = C3_RT_FEE * c3_notional
        ts_fees = ts_notional * (2 * float(tsmom.FEE_TAKER))  # 2x5bps round-trip
        ew_net = 0.5 * (c3_net + ts_net)
        ew_fees = 0.5 * (c3_fees + ts_fees)
        ew_prefee_net = ew_net + ew_fees
        ew_notional = 0.5 * (c3_notional + ts_notional)
        breakeven_bps = (ew_prefee_net / ew_notional * 10000) if ew_notional else 0.0
        fee_frac = (ew_fees / ew_prefee_net) if ew_prefee_net > 0 else float("nan")

        summary[win] = dict(
            c3_net=c3_net,
            ts_net=ts_net,
            ew=ew,
            ivm=ivm,
            ew_res=ew_res,
            iv_res=iv_res,
            c3_oosm=c3_oosm,
            ts_oosm=ts_oosm,
            c3_oosp=c3_oosp,
            ts_oosp=ts_oosp,
            iv=iv,
            ew_path=ew_path,
            ew_net=ew_net,
            ew_fees=ew_fees,
            ew_prefee_net=ew_prefee_net,
            breakeven_bps=breakeven_bps,
            fee_frac=fee_frac,
            c3_fees=c3_fees,
            ts_fees=ts_fees,
            ew_notional=ew_notional,
        )

    # ===== TASK 1 REPORT =====
    print("=" * 78)
    print("TASK 1 — STATIC ENSEMBLE (equal-weight 50/50; UNCHANGED G1-G7)")
    print("=" * 78)
    print(
        f"{'window':<9}|{'C3 net':>8}|{'TSM net':>8}|{'EW net':>8}|{'oosShrp':>8}|{'isShrp':>7}|{'PF':>6}|{'maxDD':>7}| verdict"
    )
    print("-" * 78)
    for win in ("current", "earlier"):
        s = summary[win]
        m = s["ew"]
        print(
            f"{win:<9}|{s['c3_net']:>+8.2f}|{s['ts_net']:>+8.2f}|{m['net_pnl_usd']:>+8.2f}|"
            f"{m['oos_sharpe']:>8.2f}|{m['in_sample_sharpe']:>7.2f}|{m['profit_factor']:>6.2f}|"
            f"{m['max_drawdown_pct']:>7.3f}| {'PASS' if s['ew_res'].passed else 'FAIL'}"
        )
    print(
        "\nLINEAR-MEAN EVIDENCE (per-leg OOS mean per-trade return -> blend OOS sign):"
    )
    for win in ("current", "earlier"):
        s = summary[win]
        m = s["ew"]
        print(
            f"  {win}: C3 OOS mean ret {s['c3_oosm']:+.5f} (pnl {s['c3_oosp']:+.2f}) | "
            f"TSMOM OOS mean ret {s['ts_oosm']:+.5f} (pnl {s['ts_oosp']:+.2f}) "
            f"-> blend OOS mean {m['_oos_mean_ret']:+.5f}"
        )
    print(
        "\nINVERSE-VOL weights + net (Sharpe sign identical — both legs OOS-negative):"
    )
    for win in ("current", "earlier"):
        s = summary[win]
        m = s["ivm"]
        print(
            f"  {win}: w(C3,TSMOM)=({s['iv'][0]:.2f},{s['iv'][1]:.2f}) net {m['net_pnl_usd']:+.2f} "
            f"oosShrp {m['oos_sharpe']:+.2f} -> {'PASS' if s['iv_res'].passed else 'FAIL'}"
        )
    print("\nPER-CRITERION G1..G7 (equal-weight):")
    for win in ("current", "earlier"):
        s = summary[win]
        print(
            f"  [{win}] {'PASS' if s['ew_res'].passed else 'FAIL'}: "
            + " ".join(
                f"{g}={'ok' if c['passed'] else 'XX'}"
                for g, c in sorted(s["ew_res"].criteria.items())
            )
        )

    # ===== TASK 2 REPORT =====
    print("\n" + "=" * 78)
    print("TASK 2 — ECONOMICS FLOOR (equal-weight blend, $100 book; taker)")
    print("=" * 78)
    print(
        f"{'window':<9}|{'EW net':>8}|{'EW fees':>8}|{'pre-fee':>8}|{'fee%gross':>10}|{'breakeven_RT':>13}|{'$25 net':>8}"
    )
    print("-" * 78)
    for win in ("current", "earlier"):
        s = summary[win]
        ff = s["fee_frac"]
        print(
            f"{win:<9}|{s['ew_net']:>+8.2f}|{s['ew_fees']:>8.2f}|{s['ew_prefee_net']:>+8.2f}|"
            f"{(ff * 100 if ff == ff else float('nan')):>9.1f}%|{s['breakeven_bps']:>11.1f}bp|{0.25 * s['ew_net']:>+8.3f}"
        )
    print("\nactual round-trip fees: perp taker ~10bps, perp maker ~4bps.")
    print(
        "NET SIGN is tranche-INVARIANT (%-fees scale gross & fees together); lever is fee TIER not size."
    )
    print("\nreports (equal-weight blend):")
    for win in ("current", "earlier"):
        print(f"  {summary[win]['ew_path']}")

    # ===== VERDICT / BRANCH =====
    ew_fail = not (
        summary["current"]["ew_res"].passed and summary["earlier"]["ew_res"].passed
    )
    edge_clears = all(summary[w]["ew_net"] > 0 for w in WINDOWS) and all(
        summary[w]["breakeven_bps"] > 10.0 for w in WINDOWS
    )
    print("\n" + "=" * 78)
    print(f"static ensemble graduates both windows? {'NO' if ew_fail else 'YES'}")
    print(
        f"edge clears the ~10bps taker fee floor (net>0 both windows)? {'YES' if edge_clears else 'NO'}"
    )
    if ew_fail and edge_clears:
        print(
            "=> BRANCH 2: not fee-dominated; gate construction (2mo OOS x 2 windows) is the suspect. SCOPE Option B (walk-forward)."
        )
    elif ew_fail and not edge_clears:
        print(
            "=> BRANCH 1: fee/capital-dominated. STOP the backtest loop; surface the doctrine fork."
        )
    else:
        print("=> BRANCH 3: ensemble graduates — real edge. (low prior)")


if __name__ == "__main__":
    main()
