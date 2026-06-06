"""T2 — Cross-sectional momentum, weekly rebalance, alt universe (Reactivation 2026-06-06).

FROZEN per docs/decisions/2026-06-06_reactivation_thesis_portfolio_preregistration.md
§3 T2. ONE registered harness run, seed=7, 5-part gate with Bonferroni p97.5 null.

Signal: trailing 21d return skipping the most recent 24h, ranked across U30 each
Monday 00:00 UTC. Portfolio: long top quintile, short bottom quintile, equal dollar,
weekly full rebalance, no stops. Null: random-rank quintiles (same dates/counts/turnover).

    .venv-nt/Scripts/python tools/nautilus/run_t2_xsect_momentum.py
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.nautilus import u30_data, xsect_signals
from tools.nautilus.basket_ledger import precompute_funding_matrix, simulate_basket
from tools.nautilus.null_engines import null_distribution
from tools.nautilus.xsect_walkforward import evaluate, make_folds

BOOK = 100.0
FEE_RATE = 0.0005
SEED = 7
N_NULL = 1000
WIN_START = pd.Timestamp("2023-05-28T00:00:00Z")
WIN_END = pd.Timestamp("2026-05-27T00:00:00Z")
GRAD = ROOT / "data" / "graduation"


def _mondays(start, end, valid_days) -> pd.DatetimeIndex:
    alld = pd.date_range(start, end - pd.Timedelta(days=1), freq="W-MON", tz="UTC")
    return alld[alld.isin(valid_days)]


def run_harness(null_n: int = N_NULL) -> dict:
    uni = u30_data.load_universe()
    membership = u30_data.membership_by_date(uni)
    symbols = u30_data.union_symbols(uni)
    daily_close = u30_data.load_daily_close_panel(symbols)
    funding = u30_data.load_funding(symbols)

    rebal_dates = _mondays(WIN_START, WIN_END, daily_close.index)
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
        return xsect_signals.build_t2_schedule(scores, membership, rebal_dates, BOOK)

    real_scores = xsect_signals.momentum_panel(daily_close, rebal_dates)
    real_schedule = builder(real_scores)
    real_result = simulate(real_schedule)

    null_sharpes = null_distribution(
        builder, simulate_null, rebal_dates, symbols, folds, BOOK, n=null_n, seed=SEED
    )

    verdict = evaluate(real_result, folds, null_sharpes)
    verdict.update(
        {
            "thesis": "T2_xsect_momentum",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "n_null_draws": int(null_n),
            "book_usd": BOOK,
            "fee_rate_per_side": FEE_RATE,
            "window": f"{WIN_START.date()} -> {WIN_END.date()}",
            "n_union_symbols": len(symbols),
            "n_rebalance_weeks": len(rebal_dates),
            "null_model": "random-rank quintiles (same dates/counts/weekly turnover)",
            "_data": "REAL Binance USDT-M perp 1h klines + 8h funding, point-in-time U30",
        }
    )
    return verdict


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--null-n", type=int, default=N_NULL)
    args = ap.parse_args(argv)
    GRAD.mkdir(parents=True, exist_ok=True)
    out = run_harness(args.null_n)
    path = GRAD / f"T2_xsect_momentum_{date.today().isoformat()}.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    print(f"\nwritten: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
