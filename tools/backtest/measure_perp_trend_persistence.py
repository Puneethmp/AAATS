"""Measure perp time-series trend persistence to pick the TSMOM lookback a priori.

B.1.7 Track F (2026-05-30). Picks the momentum lookback L for the perp-native
time-series-momentum trial WITHOUT touching PnL — purely from the data's own
trend-persistence structure, measured on the CURRENT window's IN-SAMPLE portion
ONLY (bars strictly before the 2026-03-28 OOS cutoff). This keeps the parameter
choice out of both test partitions (current-OOS and the entire earlier window),
so it cannot be fitting to what the graduation gate later scores.

Metric (the time-series-momentum predictive coefficient): for each candidate
lookback L (hours), at a daily (24h) rebalance cadence, compute the average of

    sign( trailing_return over [t-L, t] ) * forward_return over [t, t+24h]

across all 6 perps and all in-sample rebalance points. POSITIVE => sign of the
trailing-L return predicts the next day's direction (trend persists / momentum);
NEGATIVE => mean-reversion at that horizon. We pick the L with the strongest
POSITIVE persistence. This is one structural choice, not a Sharpe sweep.

    python tools/backtest/measure_perp_trend_persistence.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "historical"
UNIVERSE = ["BTC", "ETH", "SOL", "LINK", "AVAX", "DOT"]
IS_CUTOFF = pd.Timestamp("2026-03-28", tz="UTC")  # current-window IS/OOS boundary
REBAL_H = 24  # daily rebalance / forward-return horizon
CANDIDATES_H = [24, 48, 72, 120, 168, 240, 336, 504, 720]  # 1d..30d


def _closes(sym: str) -> pd.Series:
    df = pd.read_parquet(HIST / f"{sym}_USDT_1h_perp.parquet")
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df["ts"], utc=True)
    return df["close"].astype(float).sort_index()


def main() -> None:
    closes = {s: _closes(s) for s in UNIVERSE}
    print(f"current-window IN-SAMPLE only (< {IS_CUTOFF.date()}), {REBAL_H}h cadence\n")
    print(
        f"{'lookback_h':>11} | {'pred_coef(mean signXfwd)':>26} | {'hit_rate':>9} | {'n':>6}"
    )
    print("-" * 66)
    results = {}
    for L in CANDIDATES_H:
        vals = []
        for s in UNIVERSE:
            c = closes[s]
            c = c[c.index < IS_CUTOFF]
            arr = c.to_numpy()
            n = len(arr)
            # rebalance points: every REBAL_H bars, needs L history and 24h forward
            for t in range(L, n - REBAL_H, REBAL_H):
                trail = arr[t] / arr[t - L] - 1.0
                fwd = arr[t + REBAL_H] / arr[t] - 1.0
                if trail == 0:
                    continue
                vals.append(np.sign(trail) * fwd)
        v = np.array(vals)
        pred_coef = float(v.mean())
        hit = float((v > 0).mean())  # fraction where sign predicted fwd direction
        results[L] = (pred_coef, hit, len(v))
        print(f"{L:>11} | {pred_coef:>+26.6f} | {hit:>8.1%} | {len(v):>6}")

    best = max(results, key=lambda k: results[k][0])
    print(
        f"\nstrongest positive persistence: L={best}h "
        f"(pred_coef {results[best][0]:+.6f}, hit {results[best][1]:.1%})"
    )
    print(
        "-> use this L as the a-priori TSMOM lookback. If the best coef is <= 0, "
        "the perp universe is mean-reverting at daily cadence (momentum is the "
        "wrong class) and that itself is the finding."
    )


if __name__ == "__main__":
    main()
