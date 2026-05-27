"""C3 6-month walk-forward driver for B.1.5 Phase 4.

Five overlapping 60d windows at 30d stride across 180d of 1h bars.
For each window: 7-point slippage sweep (0, 5, 10, 15, 20, 25, 50 bps/side).

Run via: python tools/backtest/_c3_walkforward_oneoff.py
Saves: data/backtest_results/c3_walkforward_6mo_2026_05_27.json
"""

from __future__ import annotations

import io
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.backtest.c3_replay import replay_c3, summarize_trades, BTC_SYMBOL  # noqa: E402
from trading import altcoin_reversion as c3mod  # noqa: E402

HIST = ROOT / "data" / "historical"
UNIVERSE = sorted({BTC_SYMBOL, *c3mod.SYMBOLS})  # BTC + SOL + LINK + AVAX + DOT
SWEEP = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 50.0]
WARMUP = 35  # bars of indicator warmup per window (matches Phase 3.5 START)
BARS_PER_DAY = 24
WINDOW_DAYS = 60
STRIDE_DAYS = 30


def load(sym: str) -> pd.DataFrame:
    p = HIST / (sym.replace("/", "_") + "_1h.parquet")
    df = pd.read_parquet(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def align_bars() -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp]]:
    bars = {s: load(s) for s in UNIVERSE}
    common = None
    for df in bars.values():
        ts = set(df["ts"])
        common = ts if common is None else common & ts
    assert common is not None
    common_sorted = sorted(common)
    for s in bars:
        bars[s] = (
            bars[s][bars[s]["ts"].isin(common_sorted)]
            .sort_values("ts")
            .reset_index(drop=True)
        )
    return bars, common_sorted


def interp_breakeven_bps(rows: list[dict]) -> float | None:
    """Linear-interpolate the slip_bps at which pnl_usd crosses zero."""
    pts = sorted([(r["slip_bps"], r["pnl_usd"]) for r in rows])
    if pts[0][1] <= 0:
        return 0.0  # unprofitable at zero cost
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if y0 > 0 and y1 <= 0:
            if y0 == y1:
                return x0
            return float(x0 + (0.0 - y0) * (x1 - x0) / (y1 - y0))
    return None  # still positive at 50 bps — extrapolate not done


def classify_window(row0: dict, breakeven: float | None) -> str:
    sharpe = row0["sharpe"]
    win = row0["win_rate"]
    pnl0 = row0["pnl_usd"]
    if pnl0 <= 0 or breakeven is None or breakeven < 10 or sharpe <= 0.3:
        return "DEAD"
    if breakeven > 30 and sharpe > 0.8 and win > 0.45:
        return "STRONG"
    if 10 <= breakeven <= 1000 and sharpe > 0.3:
        return "MARGINAL"
    return "DEAD"


def cross_window_verdict(verdicts: list[str]) -> str:
    n = len(verdicts)
    bad = sum(1 for v in verdicts if v == "DEAD")
    good = n - bad
    if bad == 0 and good >= max(4, n - 1):
        return "ROBUST"
    if good <= 1:
        return "WINDOW-LUCKY"
    return "WINDOW-DEPENDENT"


def main() -> int:
    bars, common = align_bars()
    n = len(common)
    bars_per_window = WINDOW_DAYS * BARS_PER_DAY
    bars_per_stride = STRIDE_DAYS * BARS_PER_DAY
    print(f"Aligned bars: {n} over {(common[-1] - common[0]).days}d", flush=True)

    windows = []
    for w in range(5):
        ws = w * bars_per_stride
        we = ws + bars_per_window
        if we > n:
            print(f"W{w + 1}: end_idx {we} exceeds n={n}, stop", flush=True)
            break
        start_idx = ws + WARMUP
        end_idx = we
        print(
            f"W{w + 1}: bars[{ws}:{we}] ({common[ws].date()} to {common[we - 1].date()})  "
            f"replay_idx[{start_idx}:{end_idx}]",
            flush=True,
        )
        rows = []
        for slip in SWEEP:
            r = replay_c3(
                bars_by_symbol=bars,
                start_idx=start_idx,
                end_idx=end_idx,
                starting_capital=100.0,
                slippage_bps=slip,
                universe=list(c3mod.SYMBOLS),
            )
            s = summarize_trades(r["trades"], end_idx - start_idx)
            rows.append(
                {
                    "slip_bps": slip,
                    "n_trades": s["n_trades"],
                    "pnl_usd": round(s["pnl_usd"], 4),
                    "sharpe": round(s["sharpe"], 3),
                    "win_rate": round(s["win_rate"], 3),
                    "profit_factor": (
                        round(s["profit_factor"], 3)
                        if s["profit_factor"] != float("inf")
                        else "inf"
                    ),
                    "max_drawdown_pct": round(r["max_drawdown_pct"], 4),
                }
            )
            print(
                f"  slip={slip:>5} n={s['n_trades']:>3} pnl={s['pnl_usd']:+8.4f} "
                f"sh={s['sharpe']:+7.3f} win={s['win_rate']:>5.1%}",
                flush=True,
            )
        breakeven = interp_breakeven_bps(rows)
        verdict = classify_window(rows[0], breakeven)
        windows.append(
            {
                "window_id": f"W{w + 1}",
                "start_idx": ws,
                "end_idx": we,
                "start_ts": str(common[ws]),
                "end_ts": str(common[we - 1]),
                "warmup_bars": WARMUP,
                "rows": rows,
                "breakeven_bps": breakeven,
                "sharpe_at_0bps": rows[0]["sharpe"],
                "win_rate_at_0bps": rows[0]["win_rate"],
                "pnl_at_0bps_usd": rows[0]["pnl_usd"],
                "n_trades_at_0bps": rows[0]["n_trades"],
                "verdict": verdict,
            }
        )
        print(
            f"  -> verdict={verdict}  breakeven={breakeven}\n",
            flush=True,
        )

    agg = cross_window_verdict([w["verdict"] for w in windows])
    out = {
        "strategy": "c3",
        "phase": "B.1.5 phase 4 walk-forward",
        "data_window": (
            f"{common[0]} to {common[-1]} ({n} 1h bars, "
            f"{(common[-1] - common[0]).days}d)"
        ),
        "universe": UNIVERSE,
        "n_windows": len(windows),
        "window_days": WINDOW_DAYS,
        "stride_days": STRIDE_DAYS,
        "warmup_bars": WARMUP,
        "slippage_sweep_bps": SWEEP,
        "windows": windows,
        "aggregate_verdict": agg,
        "verdict_distribution": {
            "STRONG": sum(1 for w in windows if w["verdict"] == "STRONG"),
            "MARGINAL": sum(1 for w in windows if w["verdict"] == "MARGINAL"),
            "DEAD": sum(1 for w in windows if w["verdict"] == "DEAD"),
        },
    }

    out_path = ROOT / "data" / "backtest_results" / "c3_walkforward_6mo_2026_05_27.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, default=str, indent=2))
    print(f"\nSaved: {out_path}")
    print(f"\nAGGREGATE VERDICT: {agg}")
    print(f"  STRONG: {out['verdict_distribution']['STRONG']}")
    print(f"  MARGINAL: {out['verdict_distribution']['MARGINAL']}")
    print(f"  DEAD: {out['verdict_distribution']['DEAD']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
