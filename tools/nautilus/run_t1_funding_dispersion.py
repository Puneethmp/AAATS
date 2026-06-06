"""T1 — Cross-sectional alt-perp funding dispersion basket (Reactivation, 2026-06-06).

FROZEN per docs/decisions/2026-06-06_reactivation_thesis_portfolio_preregistration.md
§3 T1. ONE registered harness run, seed=7, 5-part gate with Bonferroni p97.5 null.

Two registered modes:
  --mode precheck   T1 economics pre-check (funding data ONLY): median selected-name
                    round-trip funding income vs the 10bps round-trip taker cost. If
                    median < 10bps the thesis is economically VOID (terminal, no harness).
  --mode run        full walk-forward harness (requires precheck to have passed).

Outputs commit verbatim to data/graduation/.

    .venv-nt/Scripts/python tools/nautilus/run_t1_funding_dispersion.py --mode precheck
    .venv-nt/Scripts/python tools/nautilus/run_t1_funding_dispersion.py --mode run
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.nautilus import u30_data, xsect_signals
from tools.nautilus.basket_ledger import precompute_funding_matrix, simulate_basket
from tools.nautilus.null_engines import null_distribution
from tools.nautilus.xsect_walkforward import evaluate, make_folds

BOOK = 100.0
FEE_RATE = 0.0005  # taker 5bps per side (frozen)
ROUND_TRIP_TAKER_BPS = 10.0  # 2 * 5bps — the economics pre-check hurdle
SEED = 7
N_NULL = 1000
WIN_START = pd.Timestamp("2023-05-28T00:00:00Z")
WIN_END = pd.Timestamp("2026-05-27T00:00:00Z")
GRAD = ROOT / "data" / "graduation"


def _schedule_roundtrips(schedule):
    """Yield (symbol, side, entry_ts, exit_ts, n_rebals) continuous holds from a
    schedule (list of (date, {symbol: signed_dollar}))."""
    schedule = sorted(schedule, key=lambda kv: kv[0])
    dates = [d for d, _ in schedule]
    # per symbol sign sequence
    syms = set()
    for _, w in schedule:
        syms.update(w)
    runs = []
    for s in syms:
        signs = [np.sign(w.get(s, 0.0)) for _, w in schedule]
        i = 0
        n = len(signs)
        while i < n:
            if signs[i] == 0:
                i += 1
                continue
            run_sign = signs[i]
            start = i
            while i < n and signs[i] == run_sign:
                i += 1
            end = i - 1
            runs.append(
                (
                    s,
                    "short" if run_sign < 0 else "long",
                    dates[start],
                    dates[end],
                    end - start + 1,
                )
            )
    return runs


def _build_real_schedule(funding, membership, rebal_dates):
    scores = xsect_signals.trailing_funding_mean_panel(funding, rebal_dates)
    return xsect_signals.build_t1_schedule(
        scores, membership, rebal_dates, BOOK
    ), scores


def economics_precheck() -> dict:
    """Registered funding-only pre-check. Reads funding + universe; no price/PnL."""
    uni = u30_data.load_universe()
    membership = u30_data.membership_by_date(uni)
    symbols = u30_data.union_symbols(uni)
    funding = u30_data.load_funding(symbols)
    rebal_dates = pd.DatetimeIndex(sorted(membership)).tz_convert("UTC")
    rebal_dates = rebal_dates[(rebal_dates >= WIN_START) & (rebal_dates < WIN_END)]

    schedule, _ = _build_real_schedule(funding, membership, rebal_dates)
    runs = _schedule_roundtrips(schedule)

    # per round trip: net funding income per unit notional (bps). Short receives +rate;
    # long receives -rate. Notional cancels — this is funding data only.
    incomes_bps, holds = [], []
    for sym, side, entry_d, exit_d, n_reb in runs:
        ser = funding.get(sym)
        if ser is None or len(ser) == 0:
            continue
        seg = ser[(ser.index > entry_d) & (ser.index <= exit_d + pd.Timedelta(days=1))]
        if len(seg) == 0:
            continue
        factor = 1.0 if side == "short" else -1.0
        incomes_bps.append(float(factor * seg.sum()) * 1e4)
        holds.append((exit_d - entry_d).days + 1)

    incomes = np.array(incomes_bps) if incomes_bps else np.array([0.0])
    median_income = float(np.median(incomes))
    void = median_income < ROUND_TRIP_TAKER_BPS
    out = {
        "thesis": "T1_funding_dispersion",
        "check": "economics_precheck",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_round_trips": len(incomes_bps),
        "median_roundtrip_funding_income_bps": round(median_income, 4),
        "mean_roundtrip_funding_income_bps": round(float(incomes.mean()), 4),
        "p25_funding_income_bps": round(float(np.percentile(incomes, 25)), 4),
        "p75_funding_income_bps": round(float(np.percentile(incomes, 75)), 4),
        "frac_round_trips_clearing_10bps": round(
            float(np.mean(incomes >= ROUND_TRIP_TAKER_BPS)), 4
        ),
        "mean_hold_days": round(float(np.mean(holds)), 2) if holds else 0.0,
        "round_trip_taker_cost_bps": ROUND_TRIP_TAKER_BPS,
        "verdict": "ECONOMICALLY_VOID" if void else "PRECHECK_PASS",
        "_note": (
            "Funding-only registered pre-check (pre-reg §3 T1). Median selected-name "
            "round-trip funding income vs 10bps round-trip taker. VOID == same terminal "
            "standing as a harness FAIL; no PnL/price was read."
        ),
    }
    return out


def run_harness(null_n: int = N_NULL) -> dict:
    uni = u30_data.load_universe()
    membership = u30_data.membership_by_date(uni)
    symbols = u30_data.union_symbols(uni)
    daily_close = u30_data.load_daily_close_panel(symbols)
    funding = u30_data.load_funding(symbols)

    rebal_dates = pd.DatetimeIndex(sorted(membership)).tz_convert("UTC")
    rebal_dates = rebal_dates[(rebal_dates >= WIN_START) & (rebal_dates < WIN_END)]
    # restrict rebalance dates to those with price marks
    rebal_dates = rebal_dates[rebal_dates.isin(daily_close.index)]

    folds = make_folds(WIN_START, WIN_END)
    fund_mat = precompute_funding_matrix(daily_close, funding)

    def simulate(schedule):
        return simulate_basket(
            daily_close, funding, schedule, BOOK, FEE_RATE, funding_rate_mat=fund_mat
        )

    def simulate_null(schedule):
        return simulate_basket(
            daily_close,
            funding,
            schedule,
            BOOK,
            FEE_RATE,
            funding_rate_mat=fund_mat,
            compute_trades=False,
        )

    def builder(scores):
        return xsect_signals.build_t1_schedule(scores, membership, rebal_dates, BOOK)

    real_scores = xsect_signals.trailing_funding_mean_panel(funding, rebal_dates)
    real_schedule = builder(real_scores)
    real_result = simulate(real_schedule)

    null_sharpes = null_distribution(
        builder, simulate_null, rebal_dates, symbols, folds, BOOK, n=null_n, seed=SEED
    )

    verdict = evaluate(real_result, folds, null_sharpes)
    verdict.update(
        {
            "thesis": "T1_funding_dispersion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "n_null_draws": int(null_n),
            "book_usd": BOOK,
            "fee_rate_per_side": FEE_RATE,
            "window": f"{WIN_START.date()} -> {WIN_END.date()}",
            "n_union_symbols": len(symbols),
            "n_rebalance_dates": len(rebal_dates),
            "null_model": "random-quintile selection (same dates/counts/hysteresis; uniform names)",
            "_data": "REAL Binance USDT-M perp 1h klines + 8h funding, point-in-time U30",
        }
    )
    return verdict


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["precheck", "run"], required=True)
    ap.add_argument("--null-n", type=int, default=N_NULL)
    args = ap.parse_args(argv)
    GRAD.mkdir(parents=True, exist_ok=True)

    if args.mode == "precheck":
        out = economics_precheck()
        path = GRAD / f"T1_funding_dispersion_PRECHECK_{date.today().isoformat()}.json"
    else:
        out = run_harness(args.null_n)
        path = GRAD / f"T1_funding_dispersion_{date.today().isoformat()}.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    print(f"\nwritten: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
