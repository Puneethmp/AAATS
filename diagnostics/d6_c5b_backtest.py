"""
D6 — C5b Funding-Rate Arbitrage Backtest (read-only).

Replays C5b strategy logic on 12 months of Binance perpetual funding rate
history. Universe: BTC/USDT, ETH/USDT (matches live C5b's hard-coded universe).

Strategy (delta-neutral):
  Entry: funding_rate >= ENTRY_THRESHOLD (default 0.0008)
  Exit:  funding_rate <  0.0002  OR  age > 14 days
  Capital: $25/leg = $50/symbol total

Backtest assumptions:
  - Funding paid every 8H to short side when rate > 0
  - Income per payment = capital_per_leg × rate (so $25 × rate per 8H)
  - No fees, slippage, or basis risk modeled (delta-neutral assumption)

Threshold ablation: 0.0004, 0.0008, 0.0012, 0.0016

Outputs:
  /app/data/diagnostics/d6_c5b_trades_<sym>_thr<X>.csv
  /app/data/diagnostics/d6_c5b_equity_<sym>_thr<X>.csv
  /app/data/diagnostics/d6_c5b_summary.json

Run inside aaats-paper-crypto:
    docker exec aaats-paper-crypto python /app/diagnostics/d6_c5b_backtest.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request

import numpy as np
import pandas as pd

OUT = Path("/app/data/diagnostics")
OUT.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT"]   # Binance perp symbols
EXIT_RATE_THRESHOLD = 0.0002       # exit when rate falls below this
MAX_HOLD_DAYS       = 14
CAPITAL_PER_LEG     = 25.0         # USD
PAYMENTS_PER_DAY    = 3            # every 8H
ENTRY_THRESHOLDS    = [0.0004, 0.0008, 0.0012, 0.0016]

INITIAL_EQUITY = 1.0


# ----------------------------------------------------------------------------
# Data fetching — Binance public futures API
# ----------------------------------------------------------------------------
def fetch_funding_history(symbol: str, days: int = 365) -> pd.DataFrame:
    """
    Fetch funding rate history. Binance returns max 1000 records per call.
    365 days × 3 payments = 1095 records, so paginate by startTime.
    """
    base = "https://fapi.binance.com/fapi/v1/fundingRate"
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    all_rows: list = []
    cur_start = start_ms
    while cur_start < end_ms:
        params = {"symbol": symbol, "startTime": cur_start, "limit": 1000}
        url = f"{base}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "AAATS/1.0"})
        with urlopen(req, timeout=20) as r:
            batch = json.loads(r.read())
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = int(batch[-1]["fundingTime"])
        if len(batch) < 1000 or last_ts <= cur_start:
            break
        cur_start = last_ts + 1
    if not all_rows:
        return pd.DataFrame(columns=["ts", "rate"])
    df = pd.DataFrame(all_rows)
    df["ts"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["rate"] = df["fundingRate"].astype(float)
    df = df[["ts", "rate"]].drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------
# Backtest engine
# ----------------------------------------------------------------------------
def backtest(funding: pd.DataFrame, *, entry_threshold: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Event-driven on funding payment events (every 8H).

    For each event:
      1. If we hold a position, accrue income (capital_per_leg × rate)
      2. Check exit (rate < EXIT or age > MAX_HOLD)
      3. If no position, check entry (rate >= entry_threshold)

    Returns (trades_df, equity_curve_df) with equity sampled at each event.
    """
    equity = INITIAL_EQUITY
    deployed_capital = CAPITAL_PER_LEG * 2     # $50 per position
    pos: dict | None = None
    trades: list[dict] = []
    equity_rows: list[dict] = []

    for _, row in funding.iterrows():
        ts = row["ts"]
        rate = float(row["rate"])

        if pos is not None:
            # Accrue 1 payment of income (CAPITAL_PER_LEG × rate)
            payment = CAPITAL_PER_LEG * rate
            pos["total_income"] += payment
            pos["payments"] += 1

            age_days = (ts - pos["entry_ts"]).total_seconds() / 86400.0

            should_exit = False
            reason = ""
            if rate < EXIT_RATE_THRESHOLD:
                should_exit = True
                reason = f"rate_dropped({rate:.4%}<{EXIT_RATE_THRESHOLD:.4%})"
            elif age_days > MAX_HOLD_DAYS:
                should_exit = True
                reason = f"max_age({age_days:.1f}d)"

            if should_exit:
                income = pos["total_income"]
                ret_pct = income / deployed_capital
                # Compound — full deployed capital at risk
                equity *= (1.0 + ret_pct)
                trades.append({
                    "entry_ts":   pos["entry_ts"].isoformat(),
                    "exit_ts":    ts.isoformat(),
                    "entry_rate": pos["entry_rate"],
                    "exit_rate":  rate,
                    "payments":   pos["payments"],
                    "total_income_usd": round(income, 5),
                    "return_pct": round(ret_pct, 6),
                    "age_days":   round(age_days, 3),
                    "reason":     reason,
                })
                pos = None

        if pos is None:
            if rate >= entry_threshold:
                pos = {
                    "entry_ts":     ts,
                    "entry_rate":   rate,
                    "total_income": 0.0,
                    "payments":     0,
                }

        equity_rows.append({"ts": ts.isoformat(), "equity": equity})

    # Close dangling
    if pos is not None and len(funding):
        ts = funding["ts"].iloc[-1]
        rate = float(funding["rate"].iloc[-1])
        income = pos["total_income"]
        ret_pct = income / deployed_capital
        equity *= (1.0 + ret_pct)
        age_days = (ts - pos["entry_ts"]).total_seconds() / 86400.0
        trades.append({
            "entry_ts":   pos["entry_ts"].isoformat(),
            "exit_ts":    ts.isoformat(),
            "entry_rate": pos["entry_rate"],
            "exit_rate":  rate,
            "payments":   pos["payments"],
            "total_income_usd": round(income, 5),
            "return_pct": round(ret_pct, 6),
            "age_days":   round(age_days, 3),
            "reason":     "end_of_data",
        })

    return pd.DataFrame(trades), pd.DataFrame(equity_rows)


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def compute_metrics(trades: pd.DataFrame, equity: pd.DataFrame) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "trade_count": 0, "win_rate": None, "avg_return_pct": None,
            "sharpe_ratio_annualized": None, "max_drawdown_pct": None,
            "profit_factor": None,
            "final_equity": float(equity["equity"].iloc[-1]) if len(equity) else 1.0,
            "total_return_pct": 0.0,
            "avg_payments_per_trade": None,
            "avg_age_days": None,
        }

    rets = trades["return_pct"].astype(float)
    wins = rets[rets > 0]
    losses = rets[rets < 0]

    if len(losses) and abs(losses.sum()) > 0:
        profit_factor = float(wins.sum() / abs(losses.sum()))
    elif len(wins):
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    eq = equity.copy()
    eq["ts"] = pd.to_datetime(eq["ts"])
    eq = eq.set_index("ts").resample("1D").last().dropna()
    daily_ret = eq["equity"].pct_change().dropna()
    if len(daily_ret) > 5 and daily_ret.std() > 0:
        sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(365))
    else:
        sharpe = None

    eq_running_max = eq["equity"].cummax()
    drawdown = (eq["equity"] - eq_running_max) / eq_running_max
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0

    return {
        "trade_count":     int(n),
        "win_rate":        round(float((rets > 0).mean()), 4),
        "avg_return_pct":  round(float(rets.mean()) * 100, 4),
        "sharpe_ratio_annualized": round(sharpe, 3) if sharpe is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 3),
        "profit_factor":   round(profit_factor, 3) if profit_factor != float("inf") else "inf",
        "final_equity":    round(float(eq["equity"].iloc[-1]), 6),
        "total_return_pct": round((float(eq["equity"].iloc[-1]) - 1.0) * 100, 3),
        "avg_payments_per_trade": round(float(trades["payments"].mean()), 2),
        "avg_age_days":    round(float(trades["age_days"].mean()), 3),
    }


def verdict(m: dict) -> str:
    if m["trade_count"] is None or m["trade_count"] < 10:
        return "BROKEN"
    if m["sharpe_ratio_annualized"] is None or m["profit_factor"] is None:
        return "BROKEN"
    s = m["sharpe_ratio_annualized"]
    pf = m["profit_factor"] if m["profit_factor"] != "inf" else 99.9
    if s > 1.0 and pf > 1.3 and m["trade_count"] >= 30:
        return "VIABLE"
    if s < 0.5 or pf < 1.0:
        return "BROKEN"
    return "MARGINAL"


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main() -> int:
    print("== D6 C5b funding-rate arbitrage backtest ==")
    print(f"Universe: {SYMBOLS}")
    print(f"Entry thresholds tested: {ENTRY_THRESHOLDS}")
    print(f"Capital per leg: ${CAPITAL_PER_LEG}, total deployed per pos: ${CAPITAL_PER_LEG*2}")

    summary: dict = {"thresholds": {}}

    funding_data: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        print(f"\n  fetching funding history for {sym} ...")
        df = fetch_funding_history(sym, days=365)
        funding_data[sym] = df
        if len(df):
            print(f"    {len(df)} payments  range [{df['ts'].iloc[0].date()} .. {df['ts'].iloc[-1].date()}]")
            print(f"    rate stats: min={df['rate'].min():.4%}  max={df['rate'].max():.4%}  "
                  f"mean={df['rate'].mean():.4%}  median={df['rate'].median():.4%}")
        else:
            print("    NO DATA")

    for thr in ENTRY_THRESHOLDS:
        thr_label = f"{thr:.4f}"
        summary["thresholds"][thr_label] = {"by_symbol": {}}
        print(f"\n--- entry_threshold = {thr:.4%} ---")
        for sym in SYMBOLS:
            df = funding_data[sym]
            if df is None or len(df) == 0:
                continue
            trades, equity = backtest(df, entry_threshold=thr)
            m = compute_metrics(trades, equity)
            v = verdict(m)
            m["verdict"] = v

            label = f"{sym}_thr{thr_label.replace('.', 'p')}"
            trades.to_csv(OUT / f"d6_c5b_trades_{label}.csv", index=False)
            equity.to_csv(OUT / f"d6_c5b_equity_{label}.csv", index=False)
            summary["thresholds"][thr_label]["by_symbol"][sym] = m
            print(f"  [{sym}]  trades={m['trade_count']:3d}  WR={m['win_rate']}  "
                  f"avg={m['avg_return_pct']}%  totRet={m['total_return_pct']}%  "
                  f"sharpe={m['sharpe_ratio_annualized']}  DD={m['max_drawdown_pct']}%  "
                  f"avg_age={m['avg_age_days']}d  -> {v}")

    summary["meta"] = {
        "capital_per_leg":       CAPITAL_PER_LEG,
        "exit_rate_threshold":   EXIT_RATE_THRESHOLD,
        "max_hold_days":         MAX_HOLD_DAYS,
        "thresholds": {
            "viable_min_sharpe":  1.0,
            "viable_min_pf":      1.3,
            "viable_min_trades":  30,
        },
        "caveats": [
            "Backtest models gross yield only — no exchange fees, slippage, basis risk.",
            "Real-world fees (~0.4% round-trip on 4 legs) can eat much of the return.",
            "Funding rate is positive most of the time, so 'win rate' = ~100%.",
        ],
    }
    (OUT / "d6_c5b_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n[OK] wrote {OUT}/d6_c5b_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
