"""One-off slippage sweep driver for B.1.5 Phase 3.5.
Run via: python tools/backtest/_slip_sweep_oneoff.py {c1|c3|c6}
Saves: data/backtest_results/slippage_sweep_<strat>_2026_05_27.json
"""

from __future__ import annotations
import sys
import json
import warnings
from pathlib import Path
import pandas as pd

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.backtest.c1_replay import replay_c1, summarize_trades as summ_c1, CRYPTO_PAIR  # noqa: E402
from tools.backtest.c3_replay import replay_c3, summarize_trades as summ_c3, BTC_SYMBOL  # noqa: E402
from tools.backtest.c6_replay import (  # noqa: E402
    replay_c6,
    summarize_trades as summ_c6,
    SYMBOLS as C6_SYMBOLS,
)
from trading import altcoin_reversion as c3mod  # noqa: E402

HIST = ROOT / "data" / "historical"


def load(sym):
    p = HIST / (sym.replace("/", "_") + "_1h.parquet")
    df = pd.read_parquet(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


NEEDED = sorted(
    {BTC_SYMBOL, "ETH/USDT", "SOL/USDT", "LINK/USDT", "AVAX/USDT", "DOT/USDT"}
)
bars = {s: load(s) for s in NEEDED}
common = None
for df in bars.values():
    s = set(df["ts"])
    common = s if common is None else common & s
common = sorted(common)
for s in bars:
    bars[s] = (
        bars[s][bars[s]["ts"].isin(common)].sort_values("ts").reset_index(drop=True)
    )
N = len(common)
START = 35
SWEEP = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 50.0]

strat = sys.argv[1] if len(sys.argv) > 1 else "c3"
# Allow per-strategy subset of sweep to fit in time budget
if len(sys.argv) > 2:
    SWEEP = [float(x) for x in sys.argv[2].split(",")]
rows = []
for slip in SWEEP:
    if strat == "c1":
        r = replay_c1(
            bars_by_symbol=bars,
            start_idx=START,
            end_idx=N,
            starting_capital=100.0,
            slippage_bps=slip,
            pair=CRYPTO_PAIR,
        )
        s = summ_c1(r["trades"], N - START)
    elif strat == "c3":
        r = replay_c3(
            bars_by_symbol=bars,
            start_idx=START,
            end_idx=N,
            starting_capital=100.0,
            slippage_bps=slip,
            universe=list(c3mod.SYMBOLS),
        )
        s = summ_c3(r["trades"], N - START)
    elif strat == "c6":
        r = replay_c6(
            bars_by_symbol=bars,
            start_idx=START,
            end_idx=N,
            starting_capital=100.0,
            slippage_bps=slip,
            symbols=list(C6_SYMBOLS),
        )
        s = summ_c6(r["trades"], N - START)
    rows.append(
        {
            "slip_bps": slip,
            "n_trades": s["n_trades"],
            "pnl_usd": round(s["pnl_usd"], 4),
            "sharpe": round(s["sharpe"], 3),
            "win_rate": round(s["win_rate"], 3),
            "pf": (
                round(s["profit_factor"], 3)
                if s["profit_factor"] != float("inf")
                else "inf"
            ),
        }
    )

OUT = ROOT / "data" / "backtest_results"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / f"slippage_sweep_{strat}_2026_05_27.json").write_text(
    json.dumps(
        {
            "strategy": strat,
            "data_window": f"{common[0]} → {common[-1]} ({N} 1h bars)",
            "rows": rows,
        },
        default=str,
        indent=2,
    )
)
print(f"== {strat} sweep ==")
print(f"{'slip':>5} {'n':>4} {'pnl':>9} {'sharpe':>8} {'win':>6} {'pf':>6}")
for r in rows:
    print(
        f"{r['slip_bps']:>5} {r['n_trades']:>4} {r['pnl_usd']:>+9.4f} {r['sharpe']:>+8.3f} {r['win_rate']:>6.1%} {str(r['pf']):>6}"
    )
