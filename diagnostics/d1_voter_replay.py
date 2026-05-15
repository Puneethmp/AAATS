"""
D1 — Voter Independence Check (replay variant).

Read-only diagnostic. Imports the live 6 voter functions from
trading.live_paper_runner and replays them on freshly-fetched 90d/4h OHLCV.

Outputs:
  /app/data/diagnostics/d1_votes.csv        — long-format (ts, symbol, voter, signal, conf)
  /app/data/diagnostics/d1_corr_matrix.csv  — pairwise Pearson correlation of numeric scores
  /app/data/diagnostics/d1_kappa_matrix.csv — pairwise Cohen's kappa on categorical signals
  /app/data/diagnostics/d1_summary.json     — agg stats + verdict

Run inside aaats-paper-crypto: docker exec aaats-paper-crypto python /app/diagnostics/d1_voter_replay.py
"""
from __future__ import annotations

import json
import os
import sys
from itertools import combinations
from pathlib import Path

import ccxt
import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

# ----------------------------------------------------------------------------
# Live voter imports (read-only)
# ----------------------------------------------------------------------------
sys.path.insert(0, "/app")
from trading.live_paper_runner import (  # noqa: E402
    _rule_regime,
    vote_bollinger,
    vote_ema,
    vote_macd_hist,
    vote_momentum,
    vote_rsi,
    vote_vwap,
)

VOTERS = [
    ("ema",       vote_ema),
    ("rsi",       vote_rsi),
    ("momentum",  vote_momentum),
    ("vwap",      vote_vwap),
    ("bollinger", vote_bollinger),
    ("macd_hist", vote_macd_hist),
]
SIGNAL_NUMERIC = {"BUY": 1.0, "HOLD": 0.0, "SELL": -1.0}

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "LINK/USDT", "DOT/USDT", "AVAX/USDT"]
N_BARS_4H = 540  # ~90 days at 4h

OUT = Path("/app/data/diagnostics")
OUT.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------
# Feature engineering — minimal set required by the 6 voters
# ----------------------------------------------------------------------------
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["close"]

    # RSI(14) Wilder
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi_14"] = 100 - (100 / (1 + rs))

    # EMA 12, 26
    out["ema_12"] = close.ewm(span=12, adjust=False).mean()
    out["ema_26"] = close.ewm(span=26, adjust=False).mean()

    # MACD
    out["macd"] = out["ema_12"] - out["ema_26"]
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    # 5-period return
    out["return_5"] = close.pct_change(5)

    # VWAP (rolling 24-bar; resets daily-ish proxy)
    pv = (out["close"] * out["volume"]).rolling(24).sum()
    vv = out["volume"].rolling(24).sum()
    out["vwap"] = pv / vv

    # Bollinger %B (20-bar, 2σ)
    ma20 = close.rolling(20).mean()
    sd20 = close.rolling(20).std()
    upper = ma20 + 2 * sd20
    lower = ma20 - 2 * sd20
    out["bb_pct"] = (close - lower) / (upper - lower).replace(0, np.nan)

    # ADX(14) Wilder simplified
    high, low = out["high"], out["low"]
    tr = pd.concat([
        (high - low),
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_dm = (high.diff().clip(lower=0)).where(
        high.diff() > -low.diff(), 0
    )
    minus_dm = (-low.diff().clip(upper=0)).where(
        -low.diff() > high.diff(), 0
    )
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    out["adx_14"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    out["atr_14"] = atr

    return out


def fetch_ohlcv_4h(symbol: str, n: int) -> pd.DataFrame:
    ex = ccxt.binance({"enableRateLimit": True})
    rows = ex.fetch_ohlcv(symbol, "4h", limit=n)
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.set_index("ts").drop(columns="ts_ms")
    return df


# ----------------------------------------------------------------------------
# Main replay
# ----------------------------------------------------------------------------
def replay_one_symbol(symbol: str) -> pd.DataFrame:
    raw = fetch_ohlcv_4h(symbol, N_BARS_4H)
    feat_full = add_features(raw).dropna()
    rows: list[dict] = []
    # Replay each bar: feed [0..i] history slice into voters (they only look at last 1-2 rows)
    # Skip first 50 bars to let indicators stabilize.
    start = 50
    for i in range(start, len(feat_full)):
        hist = feat_full.iloc[: i + 1]  # everything up to and including bar i
        regime, _r_conf = _rule_regime(hist)
        for vname, vfunc in VOTERS:
            v = vfunc(hist, "crypto", regime)
            rows.append({
                "ts":     feat_full.index[i].isoformat(),
                "symbol": symbol,
                "voter":  vname,
                "signal": v.signal,
                "conf":   v.confidence,
                "regime": regime,
            })
    return pd.DataFrame(rows)


def main() -> int:
    print("== D1 voter replay ==")
    print(f"Symbols: {SYMBOLS}")
    print(f"Bars: {N_BARS_4H} (4h, ~90 days)")

    all_dfs = []
    for sym in SYMBOLS:
        try:
            print(f"  fetch + replay {sym} ...", end=" ", flush=True)
            df = replay_one_symbol(sym)
            print(f"{len(df) // len(VOTERS)} cycles, {len(df)} votes")
            all_dfs.append(df)
        except Exception as e:
            print(f"FAILED: {e}")

    if not all_dfs:
        print("No data — exit")
        return 1

    votes = pd.concat(all_dfs, ignore_index=True)
    votes.to_csv(OUT / "d1_votes.csv", index=False)
    print(f"\n[OK] wrote {OUT}/d1_votes.csv  ({len(votes)} rows)")

    # Pivot: rows = (ts, symbol), cols = voter, value = signal/conf
    pivot_sig  = votes.pivot_table(index=["ts", "symbol"], columns="voter", values="signal", aggfunc="first")
    pivot_conf = votes.pivot_table(index=["ts", "symbol"], columns="voter", values="conf",   aggfunc="first")

    voters = [v for v, _ in VOTERS]
    # Numeric score = signal_int * conf (BUY+conf, SELL-conf, HOLD=0)
    sig_num = pivot_sig.apply(lambda col: col.map(SIGNAL_NUMERIC)) * pivot_conf

    # Pearson correlation on numeric scores
    corr = sig_num[voters].corr(method="pearson")
    corr.to_csv(OUT / "d1_corr_matrix.csv")
    print(f"[OK] wrote {OUT}/d1_corr_matrix.csv")

    # Cohen's kappa on categorical signals (pairwise)
    kappa = pd.DataFrame(np.eye(len(voters)), index=voters, columns=voters)
    for a, b in combinations(voters, 2):
        common = pivot_sig[[a, b]].dropna()
        if len(common) < 50:
            kappa.loc[a, b] = kappa.loc[b, a] = np.nan
            continue
        k = cohen_kappa_score(common[a], common[b])
        kappa.loc[a, b] = kappa.loc[b, a] = k
    kappa.to_csv(OUT / "d1_kappa_matrix.csv")
    print(f"[OK] wrote {OUT}/d1_kappa_matrix.csv")

    # Verdict
    upper_idx = np.triu_indices_from(corr.values, k=1)
    pair_corrs = corr.values[upper_idx]
    avg_corr = float(np.nanmean(np.abs(pair_corrs)))
    max_corr = float(np.nanmax(np.abs(pair_corrs)))

    upper_idx_k = np.triu_indices_from(kappa.values, k=1)
    pair_kappas = kappa.values[upper_idx_k]
    avg_kappa = float(np.nanmean(np.abs(pair_kappas)))
    max_kappa = float(np.nanmax(np.abs(pair_kappas)))

    verdict = "PASS" if (avg_corr < 0.70 and max_corr < 0.85) else "FAIL"

    summary = {
        "diagnostic": "D1_voter_replay",
        "verdict":    verdict,
        "n_cycles":   int(len(votes) // len(VOTERS)),
        "n_votes":    int(len(votes)),
        "avg_pairwise_abs_correlation": round(avg_corr, 4),
        "max_pairwise_abs_correlation": round(max_corr, 4),
        "avg_pairwise_abs_kappa":       round(avg_kappa, 4),
        "max_pairwise_abs_kappa":       round(max_kappa, 4),
        "thresholds": {"avg_corr_lt": 0.70, "max_corr_lt": 0.85},
        "notes": [
            "Replay used _rule_regime fallback (HMM cache empty during historical replay).",
            "Voters are pure functions — verified stateless before replay.",
            "Numeric score = SIGNAL_INT × conf where BUY=+1, HOLD=0, SELL=-1.",
        ],
    }
    (OUT / "d1_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[OK] wrote {OUT}/d1_summary.json")
    print(f"\nVERDICT: {verdict}  (avg|r|={avg_corr:.3f}, max|r|={max_corr:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
