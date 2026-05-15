"""
D3 — Stat-Arb Pair Scanner.

Read-only diagnostic. Scans all symbol pairs on 90d/4h OHLCV for:
  - Engle-Granger cointegration p-value
  - 30d rolling Pearson correlation (last value)
  - Current spread z-score (window=30 to match live stat_arb)

Per user modification #3: also computes a rolling 30d Engle-Granger p-value
series for BTC/ETH over the entire 90-day window. This determines whether
the pair was ever cointegrated recently or whether the strategy assumption
was wrong from day one.

Outputs:
  /app/data/diagnostics/d3_pair_rankings.csv   — sorted by p-value asc
  /app/data/diagnostics/d3_btc_eth_rolling.csv — daily-ish rolling EG p-values for BTC/ETH
  /app/data/diagnostics/d3_summary.json        — verdict + tradeable pairs

Run inside aaats-paper-crypto:
    docker exec aaats-paper-crypto python /app/diagnostics/d3_pair_scanner.py
"""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

OUT = Path("/app/data/diagnostics")
OUT.mkdir(parents=True, exist_ok=True)

CRYPTO_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "LINK/USDT", "DOT/USDT", "AVAX/USDT"]
N_BARS_4H = 540  # ~90 days
WINDOW_Z = 30   # spread z-score window (matches live trading.stat_arb)

# Live stat_arb thresholds we're checking against
P_VALUE_THRESHOLD = 0.05
CORR_THRESHOLD    = 0.80


def fetch_ohlcv_4h(symbol: str, n: int) -> pd.DataFrame:
    ex = ccxt.binance({"enableRateLimit": True})
    rows = ex.fetch_ohlcv(symbol, "4h", limit=n)
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df.set_index("ts").drop(columns="ts_ms")


def engle_granger(s1: pd.Series, s2: pd.Series) -> float:
    """Returns p-value of Engle-Granger cointegration test (lower = more cointegrated)."""
    aligned = pd.concat([s1, s2], axis=1).dropna()
    if len(aligned) < 30:
        return 1.0
    try:
        _t, p, _crit = coint(aligned.iloc[:, 0], aligned.iloc[:, 1])
        return float(p)
    except Exception:
        return 1.0


def spread_zscore(s1: pd.Series, s2: pd.Series, window: int = WINDOW_Z) -> float:
    aligned = pd.concat([s1, s2], axis=1).dropna()
    if len(aligned) < window + 5:
        return np.nan
    # Hedge ratio via OLS (consistent with simple stat-arb baseline)
    x = aligned.iloc[:, 1].values
    y = aligned.iloc[:, 0].values
    beta = float(np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1)) if np.var(x) > 0 else 1.0
    spread = pd.Series(y - beta * x, index=aligned.index)
    rolling_mean = spread.rolling(window).mean()
    rolling_std  = spread.rolling(window).std()
    z = (spread.iloc[-1] - rolling_mean.iloc[-1]) / rolling_std.iloc[-1]
    return float(z) if not np.isnan(z) else np.nan


def rolling_corr(s1: pd.Series, s2: pd.Series, window: int = 30 * 6) -> float:
    """Last value of rolling Pearson correlation. window in 4h-bars (30d≈180 bars)."""
    aligned = pd.concat([s1, s2], axis=1).dropna()
    if len(aligned) < window + 5:
        return np.nan
    return float(aligned.iloc[:, 0].rolling(window).corr(aligned.iloc[:, 1]).iloc[-1])


def rolling_eg_pvalue(s1: pd.Series, s2: pd.Series, window: int = 30 * 6) -> pd.Series:
    """30-day rolling Engle-Granger p-value series."""
    aligned = pd.concat([s1, s2], axis=1).dropna()
    out = pd.Series(index=aligned.index, dtype=float)
    for i in range(window, len(aligned)):
        win = aligned.iloc[i - window: i]
        try:
            _t, p, _ = coint(win.iloc[:, 0], win.iloc[:, 1])
            out.iloc[i] = p
        except Exception:
            out.iloc[i] = np.nan
    return out.dropna()


def main() -> int:
    print("== D3 stat-arb pair scanner ==")

    # --- Fetch all close series ---
    closes: dict[str, pd.Series] = {}
    for sym in CRYPTO_SYMBOLS:
        try:
            df = fetch_ohlcv_4h(sym, N_BARS_4H)
            closes[sym] = df["close"].rename(sym)
            print(f"  {sym}: {len(df)} bars  range [{df.index[0].date()} .. {df.index[-1].date()}]")
        except Exception as e:
            print(f"  FAIL {sym}: {e}")

    if len(closes) < 2:
        print("Not enough symbols")
        return 1

    # --- Pairwise scan ---
    pairs = list(combinations(closes.keys(), 2))
    rows: list[dict] = []
    for a, b in pairs:
        eg_p   = engle_granger(closes[a], closes[b])
        corr30 = rolling_corr(closes[a], closes[b])
        z      = spread_zscore(closes[a], closes[b])
        passes = (eg_p < P_VALUE_THRESHOLD) and (abs(corr30) > CORR_THRESHOLD)
        rows.append({
            "pair":            f"{a} / {b}",
            "eg_pvalue":       round(eg_p, 4),
            "rolling_30d_corr": round(corr30, 4),
            "current_z_score": round(z, 4) if not np.isnan(z) else None,
            "passes_health":   passes,
        })

    rankings = pd.DataFrame(rows).sort_values("eg_pvalue")
    rankings.to_csv(OUT / "d3_pair_rankings.csv", index=False)
    print(f"\n[OK] wrote {OUT}/d3_pair_rankings.csv")
    print(rankings.to_string(index=False))

    # --- Rolling EG p-value for BTC/ETH (per modification #3) ---
    print("\nComputing rolling 30d Engle-Granger p-value for BTC/ETH ...")
    if "BTC/USDT" in closes and "ETH/USDT" in closes:
        rolling_p = rolling_eg_pvalue(closes["BTC/USDT"], closes["ETH/USDT"])
        rolling_p.index.name = "ts"
        rolling_p.name = "eg_pvalue"
        rolling_p.to_csv(OUT / "d3_btc_eth_rolling.csv")
        print(f"[OK] wrote {OUT}/d3_btc_eth_rolling.csv  ({len(rolling_p)} points)")

        below_05 = (rolling_p < 0.05).sum()
        ever_cointegrated = below_05 > 0
        print(f"  Points where p < 0.05: {below_05}/{len(rolling_p)}")
        print(f"  Min p-value: {rolling_p.min():.4f}")
        print(f"  Latest p-value: {rolling_p.iloc[-1]:.4f}")
    else:
        ever_cointegrated = None
        below_05 = None
        rolling_p = pd.Series([])

    # --- Verdict ---
    tradeable = rankings[rankings["passes_health"]]
    verdict = "PASS" if len(tradeable) >= 1 else "FAIL"

    summary = {
        "diagnostic": "D3_pair_scanner",
        "verdict": verdict,
        "n_pairs_scanned": int(len(rankings)),
        "n_tradeable":     int(len(tradeable)),
        "tradeable_pairs": tradeable["pair"].tolist(),
        "best_pair_by_pvalue": rankings.iloc[0].to_dict() if len(rankings) else None,
        "btc_eth_rolling_eg": {
            "n_points": int(len(rolling_p)),
            "ever_below_005": ever_cointegrated,
            "n_below_005":    int(below_05) if below_05 is not None else None,
            "min_pvalue":     float(rolling_p.min()) if len(rolling_p) else None,
            "latest_pvalue":  float(rolling_p.iloc[-1]) if len(rolling_p) else None,
        },
        "thresholds": {
            "eg_pvalue_lt": P_VALUE_THRESHOLD,
            "corr_gt":      CORR_THRESHOLD,
        },
    }
    (OUT / "d3_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[OK] wrote {OUT}/d3_summary.json")
    print(f"\nVERDICT: {verdict}  ({len(tradeable)} tradeable pair(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
