"""
D4 — Pair stability follow-up diagnostic.

Read-only. Fetches 365d/4h OHLCV via ccxt for symbols involved in the top-3
pairs from D3, then runs rolling 30-day windows (stepped by 7d) AND
non-overlapping 30-day windows on each pair. For each window:
  - Engle-Granger cointegration p-value
  - Pearson correlation of log prices
  - Spread z-score at the END of the window (window=30 to match live stat_arb)

Outputs:
  /app/data/diagnostics/d4_<pair>_overlapping.csv     — 1 row per window
  /app/data/diagnostics/d4_<pair>_nonoverlapping.csv  — disjoint windows
  /app/data/diagnostics/d4_summary.json               — verdicts + comparison

Run inside aaats-paper-crypto:
    docker exec aaats-paper-crypto python /app/diagnostics/d4_pair_stability.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

OUT = Path("/app/data/diagnostics")
OUT.mkdir(parents=True, exist_ok=True)

# Top-3 pairs from D3 ranked by EG p-value (best → worst), plus the live BTC/ETH for reference
PAIRS = [
    ("SOL/USDT",  "AVAX/USDT"),  # D3 best (p=0.0126)
    ("BTC/USDT",  "LINK/USDT"),  # D3 #2  (p=0.1129)
    ("ETH/USDT",  "DOT/USDT"),   # D3 #3  (p=0.1564)
]

ALL_SYMBOLS = sorted({s for pair in PAIRS for s in pair})

# Window config
N_BARS_4H_YEAR = 365 * 6     # 2190 bars
WINDOW_DAYS    = 30
WINDOW_BARS    = WINDOW_DAYS * 6   # 4h bars in 30 days = 180
STEP_DAYS_OVERLAP = 7
STEP_BARS_OVERLAP = STEP_DAYS_OVERLAP * 6  # 42

P_THRESHOLD    = 0.05
CORR_THRESHOLD = 0.80


def fetch_year_4h(symbol: str) -> pd.DataFrame:
    """Fetch ~365 days of 4h candles. Binance limits 1000 per call so paginate."""
    ex = ccxt.binance({"enableRateLimit": True})
    rows: list[list] = []
    # Newest-first pagination: fetch 1000 → step back by 1000 × 4h = 4000h ≈ 167d
    # Two calls cover ~330 days, three calls cover ~500 days
    since = None
    last_ts = ex.milliseconds()
    while len(rows) < N_BARS_4H_YEAR:
        # ccxt fetch_ohlcv with since= returns bars with ts >= since
        target_since = last_ts - 1000 * 4 * 3600 * 1000  # 1000 bars × 4h
        batch = ex.fetch_ohlcv(symbol, "4h", since=target_since, limit=1000)
        if not batch:
            break
        rows = batch + rows  # prepend — older bars first when concatenated
        oldest_ts_in_batch = batch[0][0]
        if oldest_ts_in_batch >= last_ts:
            break  # no progress
        last_ts = oldest_ts_in_batch - 1
        if len(batch) < 1000:
            break
    # Dedupe + sort
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset="ts_ms").sort_values("ts_ms")
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.set_index("ts").drop(columns="ts_ms")
    # Keep only the most recent N_BARS_4H_YEAR bars
    return df.iloc[-N_BARS_4H_YEAR:]


def engle_granger_pvalue(s1: pd.Series, s2: pd.Series) -> float:
    aligned = pd.concat([s1, s2], axis=1).dropna()
    if len(aligned) < 30:
        return 1.0
    try:
        _t, p, _crit = coint(aligned.iloc[:, 0], aligned.iloc[:, 1])
        return float(p)
    except Exception:
        return 1.0


def end_window_zscore(s1: pd.Series, s2: pd.Series) -> float:
    """Spread z-score at the last point of the window (window=30 bars rolling)."""
    aligned = pd.concat([s1, s2], axis=1).dropna()
    if len(aligned) < 35:
        return float("nan")
    x = aligned.iloc[:, 1].values
    y = aligned.iloc[:, 0].values
    var_x = float(np.var(x, ddof=1))
    beta = float(np.cov(x, y, ddof=1)[0, 1] / var_x) if var_x > 0 else 1.0
    spread = pd.Series(y - beta * x, index=aligned.index)
    rm = spread.rolling(30).mean().iloc[-1]
    rs = spread.rolling(30).std().iloc[-1]
    return float((spread.iloc[-1] - rm) / rs) if rs and not np.isnan(rs) else float("nan")


def rolling_stats(s1: pd.Series, s2: pd.Series, *, step_bars: int, label: str) -> pd.DataFrame:
    """Run windowed cointegration analysis. Returns one row per window."""
    aligned = pd.concat([s1, s2], axis=1).dropna()
    rows: list[dict] = []
    n = len(aligned)
    for start in range(0, n - WINDOW_BARS, step_bars):
        end = start + WINDOW_BARS
        win = aligned.iloc[start:end]
        log_a = np.log(win.iloc[:, 0])
        log_b = np.log(win.iloc[:, 1])
        eg_p = engle_granger_pvalue(win.iloc[:, 0], win.iloc[:, 1])
        corr = float(log_a.corr(log_b))
        z = end_window_zscore(win.iloc[:, 0], win.iloc[:, 1])
        rows.append({
            "window_start": win.index[0].isoformat(),
            "window_end":   win.index[-1].isoformat(),
            "eg_pvalue":    round(eg_p, 4),
            "log_corr":     round(corr, 4),
            "end_z_score":  round(z, 4) if not np.isnan(z) else None,
            "passes_p":     eg_p < P_THRESHOLD,
            "passes_corr":  abs(corr) > CORR_THRESHOLD,
            "passes_both":  (eg_p < P_THRESHOLD) and (abs(corr) > CORR_THRESHOLD),
        })
    df = pd.DataFrame(rows)
    df.attrs["label"] = label
    return df


def longest_streak(bools: pd.Series, value: bool) -> int:
    """Longest consecutive run of `value` in a boolean series."""
    longest = 0
    current = 0
    for v in bools:
        if bool(v) == value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def verdict_for_pair(non_overlap: pd.DataFrame, overlap: pd.DataFrame) -> dict:
    n_non = len(non_overlap)
    pct_non_pass = float(non_overlap["passes_both"].mean() * 100) if n_non else 0.0
    median_corr = float(non_overlap["log_corr"].median()) if n_non else 0.0

    if pct_non_pass >= 60.0 and median_corr >= 0.80:
        verdict = "STABLE"
    elif pct_non_pass >= 40.0 or (median_corr >= 0.75 and pct_non_pass >= 30):
        verdict = "MARGINAL"
    else:
        verdict = "UNSTABLE"

    return {
        "verdict":            verdict,
        "n_non_overlap":      int(n_non),
        "pct_non_overlap_passes_both": round(pct_non_pass, 2),
        "n_overlap":          int(len(overlap)),
        "pct_overlap_passes_both":     round(float(overlap["passes_both"].mean() * 100), 2),
        "median_p_non_overlap":        round(float(non_overlap["eg_pvalue"].median()),  4),
        "median_corr_non_overlap":     round(median_corr, 4),
        "median_p_overlap":            round(float(overlap["eg_pvalue"].median()),      4),
        "median_corr_overlap":         round(float(overlap["log_corr"].median()),       4),
        "longest_pass_streak_overlap":  int(longest_streak(overlap["passes_both"], True)),
        "longest_fail_streak_overlap":  int(longest_streak(overlap["passes_both"], False)),
    }


def main() -> int:
    print("== D4 pair stability follow-up ==")
    print(f"Pairs: {PAIRS}")
    print(f"Window: {WINDOW_DAYS}d ({WINDOW_BARS} 4h bars)")
    print(f"Overlap step: {STEP_DAYS_OVERLAP}d ({STEP_BARS_OVERLAP} bars)")

    closes: dict[str, pd.Series] = {}
    for sym in ALL_SYMBOLS:
        try:
            print(f"  fetch {sym} ...", end=" ", flush=True)
            df = fetch_year_4h(sym)
            closes[sym] = df["close"].rename(sym)
            print(f"{len(df)} bars  range [{df.index[0].date()} .. {df.index[-1].date()}]")
        except Exception as e:
            print(f"FAIL: {e}")

    summary: dict = {"pairs": {}}
    for a, b in PAIRS:
        if a not in closes or b not in closes:
            continue
        pair_label = f"{a.replace('/', '_')}__{b.replace('/', '_')}"
        print(f"\n--- {a} / {b} ---")

        overlap = rolling_stats(closes[a], closes[b], step_bars=STEP_BARS_OVERLAP, label="overlap")
        non_overlap = rolling_stats(closes[a], closes[b], step_bars=WINDOW_BARS, label="non_overlap")

        overlap.to_csv(OUT / f"d4_{pair_label}_overlapping.csv", index=False)
        non_overlap.to_csv(OUT / f"d4_{pair_label}_nonoverlapping.csv", index=False)
        print(f"  [OK] wrote {pair_label} CSVs")

        v = verdict_for_pair(non_overlap, overlap)
        summary["pairs"][f"{a} / {b}"] = v
        print(f"  VERDICT: {v['verdict']}  "
              f"(non-overlap pass: {v['pct_non_overlap_passes_both']}%, "
              f"median corr: {v['median_corr_non_overlap']})")

    summary["thresholds"] = {
        "p_lt": P_THRESHOLD,
        "corr_gt": CORR_THRESHOLD,
        "stable_min_pct_non_overlap": 60.0,
        "stable_min_median_corr": 0.80,
    }
    (OUT / "d4_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[OK] wrote {OUT}/d4_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
