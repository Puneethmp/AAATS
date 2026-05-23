"""tools/backtest/run_b15_c3.py - end-to-end B.1.5 backtest run on C3.

Spec: docs/decisions/2026-05-22_b15_backtest_harness.md
Session-9 contract: produces data/backtest_results/c3_60d_summary.json
with the exact field set the Track E reset gate expects.

Recommendation rule (HARD-CODED per session-9 prompt):
    GO      = pnl_usd > 0 AND sharpe > 0.5 AND profitable_regime_count >= 2
              AND slippage_sensitivity_50bps_pnl_usd > 0
    PARTIAL = pnl_usd > 0 but fails any other criterion
    NO-GO   = pnl_usd <= 0 OR harness failed to complete

Three regime windows are non-overlapping 20-day spans within the 60-day
horizon, sorted by BTC realized vol (low / mid / high). profitable_regime_count
counts how many of those three windows had pnl_usd > 0 on its own replay.

Run:
    venv\\Scripts\\python tools\\backtest\\run_b15_c3.py [--days 60]
                                                       [--end-ts ISO8601]
                                                       [--force-refresh]

Writes data/backtest_results/c3_60d_summary.json and prints the summary.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import pathlib
import sys

import numpy as np
import pandas as pd

_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.backtest.c3_replay import (
    BTC_SYMBOL,
    LOOKBACK_BARS,
    replay_c3,
    summarize_trades,
)
from tools.backtest.historical_data import fetch_ohlcv
from trading import altcoin_reversion as c3

log = logging.getLogger("b15_runner")
_OUT_DIR = _ROOT / "data" / "backtest_results"


def compute_recommendation(
    pnl_usd: float,
    sharpe: float,
    profitable_regime_count: int,
    slippage_sensitivity_50bps_pnl_usd: float,
    harness_completed: bool = True,
) -> str:
    """Apply the session-9 hard-coded threshold table to the summary fields.

    Pure function. Used by the runner and by tests/test_b15_backtest_harness.py
    threshold-rules test.
    """
    if not harness_completed or pnl_usd <= 0:
        return "NO-GO"
    if (
        sharpe > 0.5
        and profitable_regime_count >= 2
        and slippage_sensitivity_50bps_pnl_usd > 0
    ):
        return "GO"
    return "PARTIAL"


def _align_bars(bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Inner-join all symbols on `ts` so all DataFrames are bar-aligned."""
    common_ts = None
    for df in bars.values():
        ts_set = set(df["ts"])
        common_ts = ts_set if common_ts is None else (common_ts & ts_set)
    if not common_ts:
        return {sym: df.iloc[0:0] for sym, df in bars.items()}
    common_sorted = sorted(common_ts)
    common_index = pd.DatetimeIndex(common_sorted)
    out: dict[str, pd.DataFrame] = {}
    for sym, df in bars.items():
        d = df[df["ts"].isin(common_index)].sort_values("ts").reset_index(drop=True)
        out[sym] = d
    return out


def _split_into_regimes(btc_df: pd.DataFrame, n_windows: int = 3) -> list[tuple[str, int, int, float]]:
    """Split BTC bars into N non-overlapping 20-day windows ranked by realized
    vol. Returns list of (label, start_idx, end_idx, vol)."""
    total = len(btc_df)
    bars_per_window = total // n_windows
    candidates: list[tuple[int, int, float]] = []
    for i in range(n_windows):
        s = i * bars_per_window
        e = (i + 1) * bars_per_window if i < n_windows - 1 else total
        slice_df = btc_df.iloc[s:e]
        if len(slice_df) < 50:
            continue
        log_ret = np.diff(np.log(slice_df["close"].values))
        vol = float(np.std(log_ret, ddof=1) * np.sqrt(24))  # daily-equiv
        candidates.append((s, e, vol))
    # Sort by vol asc and label low/mid/high
    by_vol = sorted(candidates, key=lambda t: t[2])
    labels = ["low_vol", "mid_vol", "high_vol"]
    labelled = [(labels[i] if i < len(labels) else f"window_{i}", s, e, v)
                for i, (s, e, v) in enumerate(by_vol)]
    return labelled


def run_b15_c3(
    days_back: int = 60,
    end_ts: _dt.datetime | None = None,
    force_refresh: bool = False,
    slippage_bps_sensitivity: float = 50.0,
) -> dict:
    """Full B.1.5 run on C3. Returns the summary dict that will be JSON-dumped."""
    if end_ts is None:
        end_ts = _dt.datetime.now(_dt.timezone.utc)
    elif end_ts.tzinfo is None:
        end_ts = end_ts.replace(tzinfo=_dt.timezone.utc)

    universe = list(c3.SYMBOLS)
    fetch_syms = [BTC_SYMBOL] + universe

    log.info("Fetching %dd of 1h bars for %s", days_back, fetch_syms)
    bars: dict[str, pd.DataFrame] = {}
    for sym in fetch_syms:
        df = fetch_ohlcv(sym, timeframe="1h", days_back=days_back,
                         end_ts=end_ts, force_refresh=force_refresh)
        if df.empty:
            log.error("no bars returned for %s", sym)
            return {
                "as_of": end_ts.isoformat(),
                "horizon_days": days_back,
                "trades": 0,
                "pnl_usd": 0.0,
                "sharpe": 0.0,
                "win_rate": 0.0,
                "profitable_regime_count": 0,
                "slippage_sensitivity_50bps_pnl_usd": 0.0,
                "recommendation": "NO-GO",
                "evidence": (
                    f"harness failed: empty bars for {sym} ({days_back}d 1h). "
                    f"Cannot proceed."
                ),
                "harness_completed": False,
            }
        bars[sym] = df
        log.info("  %s: %d bars [%s -> %s]", sym, len(df),
                 df["ts"].min(), df["ts"].max())

    bars = _align_bars(bars)
    btc = bars[BTC_SYMBOL]
    if len(btc) < LOOKBACK_BARS + 50:
        return {
            "as_of": end_ts.isoformat(),
            "horizon_days": days_back,
            "trades": 0,
            "pnl_usd": 0.0,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "profitable_regime_count": 0,
            "slippage_sensitivity_50bps_pnl_usd": 0.0,
            "recommendation": "NO-GO",
            "evidence": (
                f"harness failed: only {len(btc)} aligned bars (need "
                f">{LOOKBACK_BARS + 50})"
            ),
            "harness_completed": False,
        }
    log.info("Aligned: %d common bars", len(btc))

    # --- Headline 60d run (no slippage) ---
    full = replay_c3(
        bars,
        start_idx=LOOKBACK_BARS + 5,
        end_idx=len(btc),
        starting_capital=100.0,
        slippage_bps=0.0,
        universe=universe,
    )
    headline = summarize_trades(full["trades"], full["bars_evaluated"])
    log.info("Headline: %s", headline)

    # --- 50bps slippage sensitivity ---
    slip = replay_c3(
        bars,
        start_idx=LOOKBACK_BARS + 5,
        end_idx=len(btc),
        starting_capital=100.0,
        slippage_bps=slippage_bps_sensitivity,
        universe=universe,
    )
    slip_metrics = summarize_trades(slip["trades"], slip["bars_evaluated"])
    log.info("50bps slip: %s", slip_metrics)

    # --- Three regime windows ---
    regimes = _split_into_regimes(btc, n_windows=3)
    regime_results: list[dict] = []
    profitable = 0
    for label, s, e, vol in regimes:
        s_safe = max(s, LOOKBACK_BARS + 5)
        if e - s_safe < 50:
            regime_results.append({
                "label": label, "start_idx": s, "end_idx": e,
                "btc_realized_vol_daily": vol, "n_trades": 0,
                "pnl_usd": 0.0, "skipped": "too short after warmup",
            })
            continue
        rr = replay_c3(bars, s_safe, e, 100.0, 0.0, universe)
        rm = summarize_trades(rr["trades"], rr["bars_evaluated"])
        regime_results.append({
            "label": label, "start_idx": s, "end_idx": e,
            "btc_realized_vol_daily": vol, **rm,
        })
        if rm["pnl_usd"] > 0:
            profitable += 1

    rec = compute_recommendation(
        pnl_usd=headline["pnl_usd"],
        sharpe=headline["sharpe"],
        profitable_regime_count=profitable,
        slippage_sensitivity_50bps_pnl_usd=slip_metrics["pnl_usd"],
        harness_completed=True,
    )

    regime_pnl_strs = [
        f"{r['label']}=${r.get('pnl_usd', 0):.2f}" for r in regime_results
    ]
    regime_pnl_joined = ", ".join(regime_pnl_strs)
    evidence = (
        f"60d C3 replay across {universe} on 1h Binance USDT bars. "
        f"{headline['n_trades']} trades, ${headline['pnl_usd']:.2f} pnl, "
        f"sharpe {headline['sharpe']:.2f}, win-rate {headline['win_rate']:.0%}. "
        f"50bps slippage sensitivity: ${slip_metrics['pnl_usd']:.2f}. "
        f"Profitable regimes: {profitable}/{len(regime_results)} "
        f"(per-regime PnL {regime_pnl_joined}). "
        f"LIMITATIONS: replay disables BEAR regime gate (HMM not in replay) "
        f"and BTC.D fast-rise filter; both make replay PERMISSIVE (it allows "
        f"entries production would skip). Recommendation is therefore an "
        f"upper bound -- live behavior may underperform. Slippage / fees / "
        f"reconciler dust filters all set to zero in the base run; the 50bps "
        f"sensitivity gives one data point on slippage sensitivity but "
        f"production also has spread + exchange fees not modeled here."
    )

    summary = {
        "as_of": end_ts.isoformat(),
        "horizon_days": days_back,
        "trades": headline["n_trades"],
        "pnl_usd": round(headline["pnl_usd"], 4),
        "sharpe": round(headline["sharpe"], 4),
        "win_rate": round(headline["win_rate"], 4),
        "profitable_regime_count": profitable,
        "slippage_sensitivity_50bps_pnl_usd": round(slip_metrics["pnl_usd"], 4),
        "recommendation": rec,
        "evidence": evidence,
        "_metadata": {
            "universe": universe,
            "btc_symbol": BTC_SYMBOL,
            "starting_capital_usd": 100.0,
            "bar_timeframe": "1h",
            "lookback_bars": LOOKBACK_BARS,
            "n_aligned_bars": len(btc),
            "headline_metrics": headline,
            "slip_50bps_metrics": slip_metrics,
            "regime_results": regime_results,
            "harness_completed": True,
        },
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--end-ts", default=None, help="ISO8601 UTC, defaults to now")
    p.add_argument("--force-refresh", action="store_true",
                   help="re-fetch OHLCV ignoring on-disk cache")
    p.add_argument("--out", default=str(_OUT_DIR / "c3_60d_summary.json"))
    args = p.parse_args(argv)

    end_ts = None
    if args.end_ts:
        end_ts = _dt.datetime.fromisoformat(args.end_ts.replace("Z", "+00:00"))

    summary = run_b15_c3(
        days_back=args.days,
        end_ts=end_ts,
        force_refresh=args.force_refresh,
    )

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("=" * 70)
    print(f"  wrote {out_path}")
    print("=" * 70)
    print(f"  trades:            {summary['trades']}")
    print(f"  pnl_usd:           {summary['pnl_usd']:+.2f}")
    print(f"  sharpe:            {summary['sharpe']:+.3f}")
    print(f"  win_rate:          {summary['win_rate']:.1%}")
    print(f"  profitable_regimes:{summary['profitable_regime_count']}")
    print(f"  50bps slip pnl:    {summary['slippage_sensitivity_50bps_pnl_usd']:+.2f}")
    print(f"  recommendation:    {summary['recommendation']}")
    print("=" * 70)
    print(f"  evidence: {summary['evidence']}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
